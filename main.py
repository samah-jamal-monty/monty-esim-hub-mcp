import argparse
import atexit
import concurrent.futures
import os
from typing import List

from fastapi import FastAPI
from fastmcp import FastMCP
from loguru import logger

from config.utils import send_email, generate_qr_code
from dto.bundle import Bundle

mcp = FastMCP("Esim Hub Management API")
api = FastAPI()

# Module-level executor (shared/static across imports/instances)
_email_executor: concurrent.futures.ThreadPoolExecutor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="email-sender"
)

# Ensure the executor is cleanly shutdown when the process exits
atexit.register(lambda: _email_executor.shutdown(wait=False))


@api.get("/")
def health():
    return {"status": "ok"}


# Mount MCP HTTP transport on /mcp instead of /
# api.mount("/mcp", mcp.http_app())
# app = api


@mcp.prompt
def user_journey() -> str:
    return (
        "You are an assistant for helping users find and purchase eSIM bundles from the Esim Hub service. "
        "Follow these steps to assist the user:\n"
        "1) Greet the user and ask him for what bundle he is looking for.\n"
        "2) Provide the user with available bundle options ( you can use the search_bundle tool).\n"
        "3) Ask the user to select a bundle by its code or index number (1,2,3).\n"
        "4) Ask the user for his email address to proceed with the purchase.\n"
        "5) Use the purchase_bundle_and_send_activation tool to complete the purchase and email the activation details: \n"
        "   - for the bundle code, you can use the selected bundle from step 3.\n"
        "6) Confirm to the user that the activation details have been sent to his email.\n"
        "7) User can also ask for his order history by providing his email (use get_order_history tool).\n"
        "Always ensure to validate user inputs and handle errors gracefully."
    )


@mcp.resource("resource://greeting")
def get_greeting() -> str:
    """Provides a simple greeting message."""
    return "Hello, welcome to the eSIM Hub! What bundle are you looking for today?"


@mcp.tool
async def get_all_bundles() -> List[Bundle]:
    """Fetch all bundles from the Esim Hub."""
    from config.utils import esim_hub_service_instance
    service = esim_hub_service_instance()
    bundles = await service.get_all_bundles()
    # Ensure JSON-serializable return:
    # If Bundle is Pydantic v2:
    return [b.model_dump() for b in bundles]


@mcp.tool
async def search_bundles(keyword: str = None, country_name: str = None, gprs_from: str = None, gprs_to: str = None,
                         currency_code: str = None, validity: str = None) -> List[Bundle]:
    """Search bundles from the Esim Hub.
        - keyword is optional.
        - gprs from and gprs to are in MB or GB (e.g., '500MB', '2GB').
        - validity is in days or years (e.g., '30 days', '1 year').
        - country_name is optional.
        - currency_code is optional.
    """
    from config.utils import esim_hub_service_instance
    service = esim_hub_service_instance()
    return await service.search_bundles(search_keyword=keyword, country_name=country_name, gprs_from=gprs_from,
                                        gprs_to=gprs_to, currency_code=currency_code, validity=validity)


@mcp.tool
async def purchase_bundle_and_send_activation(user_email: str, bundle_code: str) -> dict:
    """End-to-end: purchase bundle, fetch activation code, build activation URL, and email it to the user."""
    from config.utils import esim_hub_service_instance
    from email_validator import validate_email, EmailNotValidError

    # Validate email
    try:
        user_email = validate_email(user_email, check_deliverability=False).normalized
    except EmailNotValidError as e:
        return {"success": False, "error": f"Invalid email: {str(e)}"}

    service = esim_hub_service_instance()

    # 1) Create order
    order_result = await service.purchase_bundle(bundle_code, user_email)
    if not order_result.get("success"):
        return {"success": False, "error": order_result.get("error", "Failed to create order")}

    order_data = (order_result.get("response") or {}).get("data") or {}
    order_id = order_data.get("orderId")
    # Response field uses 'smdpAdress' (note spelling). Also check a common variant 'smdpAddress'.
    smdp_address = order_data.get("smdpAdress") or order_data.get("smdpAddress")

    if not order_id or not smdp_address:
        return {"success": False, "error": "Order response missing orderId or SMDP+ address."}

    # 2) Fetch activation code
    activation_code = await service.get_activation_code(order_id)
    if not activation_code:
        return {"success": False, "error": "Failed to retrieve activation code."}

    # 3) Build activation URL and email it
    activation_url = f"LPA:1${smdp_address}${activation_code}"
    qr = generate_qr_code(activation_url)
    # Email the activation URL; schedule it in background to avoid delaying the response
    try:
        subject = "Your eSIM Activation Details"
        body = (
            f"Dear User,<br><br>"
            f"SMDP+ Address: <b>{smdp_address}</b><br>"
            f"Activation Code: <b>{activation_code}</b><br><br>"
            f"Activation URL:<br><a href='{activation_url}'>{activation_url}</a><br><br>"
            f"You can scan this URL with your device's eSIM manager to install the profile."
            f"<br><br>Best regards,<br>eSIM Support Team"
        )
        # schedule send_email on the shared executor
        # _send_email_in_background(subject=subject, html_content=body, recipients=user_email)
        try:
            send_email(subject=subject, html_content=body, recipients=user_email.replace(" ", ""), attachment=qr)
            emailed = True
        except Exception as e:
            logger.error(f"Immediate send_email failed, scheduling in background: {str(e)}")
            emailed = False
    except Exception as e:
        logger.error(f"Failed to schedule activation email to {user_email}: {str(e)}")
        emailed = False

    return {
        "success": True,
        "orderId": order_id,
        "smdp_address": smdp_address,
        "activation_code": activation_code,
        "activation_url": activation_url,
        "email_sent": emailed,
    }


# Background email sender helper so sending doesn't block the request/agent
def _send_email_in_background(subject: str, html_content: str, recipients: str | list[str] | None = None):
    """Submit send_email to the module-level executor and attach a done callback to log errors.

    Returns the Future object so callers can inspect result if needed. The scheduling is non-blocking.
    """

    def _call_send_email():
        # This runs in a worker thread.
        send_email(subject=subject, html_content=html_content, recipients=recipients)

    future = _email_executor.submit(_call_send_email)

    def _on_done(fut: concurrent.futures.Future):
        try:
            # Will re-raise any exception raised by send_email so we can log it
            fut.result()
        except Exception:
            logger.exception("Background send_email failed for recipients=%s", recipients)

    future.add_done_callback(_on_done)
    return future


@mcp.tool
async def send_activation_url_via_email(user_email: str, activation_url: str) -> bool:
    """Send the activation URL (activation_code + SMDP Address) via email to the user."""
    # Basic email validation for safety
    try:
        from email_validator import validate_email
        user_email = validate_email(user_email, check_deliverability=False).normalized
    except Exception:
        return False

    subject = "Your eSIM Activation QR Code"
    body = (
        f"Dear User,<br><br>Your eSIM activation URL is:<br>"
        f"<a href='{activation_url}'>{activation_url}</a>"
        f"<br><br>Best regards,<br>eSIM Support Team"
    )
    try:
        # schedule send_email on the shared executor so this call returns quickly
        _send_email_in_background(subject=subject, html_content=body, recipients=user_email)
        return True
    except Exception:
        return False


@mcp.tool
async def get_order_history(user_email: str) -> List[dict]:
    """Get order history for a given user email."""
    from config.utils import esim_hub_service_instance
    service = esim_hub_service_instance()
    return await service.get_order_history(user_email)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server_type", type=str, default="sse", choices=["sse", "stdio", "http", "stream"])
    # Default the port from environment for Render; fallback to 8181 locally
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 8181)))
    args = parser.parse_args()

    # Bind to all interfaces for Render
    mcp.run(transport=args.server_type, host="0.0.0.0", port=args.port)
