import argparse
import asyncio
import atexit
import concurrent.futures
import os
from typing import List

from fastmcp import FastMCP, Context
from loguru import logger
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from config.oauth_provider import EsimHubOAuthProvider
from config.utils import send_email, generate_qr_code, get_token
from dto.bundle import Bundle
from services import stripe_service

# OAuth authorization server so Claude Desktop / claude.ai can connect as a
# custom connector; the Client Secret the user enters is passed through as their
# mm-hub API key (see config/oauth_provider.py)
mcp = FastMCP(
    "Esim Hub Management API",
    auth=EsimHubOAuthProvider(base_url=os.getenv("MCP_BASE_URL", "https://esim-hub-mcp.onrender.com")),
)

# Module-level executor (shared/static across imports/instances)
_email_executor: concurrent.futures.ThreadPoolExecutor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="email-sender"
)

# Ensure the executor is cleanly shutdown when the process exits
atexit.register(lambda: _email_executor.shutdown(wait=False))


@mcp.custom_route("/", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/payment/success", methods=["GET"])
async def payment_success(request: Request) -> HTMLResponse:
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;text-align:center;padding-top:4rem'>"
        "<h1>✅ Payment received</h1>"
        "<p>Go back to your Claude conversation and confirm the payment to receive your eSIM.</p>"
        "</body></html>"
    )


@mcp.custom_route("/payment/webhook", methods=["POST"])
async def stripe_webhook(request: Request) -> JSONResponse:
    """Signature-verified Stripe webhook. Records payment events; fulfillment itself
    happens in purchase_bundle_and_send_activation, which re-verifies with Stripe."""
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = await asyncio.to_thread(stripe_service.parse_webhook_event, payload, signature)
    except Exception as e:
        logger.warning(f"Rejected Stripe webhook: {str(e)}")
        return JSONResponse({"error": "invalid signature"}, status_code=400)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session["metadata"] if "metadata" in session else None
        logger.info(
            f"payment completed: session={session['id']} "
            f"bundle={stripe_service.metadata_value(metadata, 'bundle_code')} "
            f"email={stripe_service.metadata_value(metadata, 'user_email')}"
        )
    else:
        logger.info(f"stripe webhook event: {event['type']}")
    return JSONResponse({"received": True})


@mcp.custom_route("/payment/cancel", methods=["GET"])
async def payment_cancel(request: Request) -> HTMLResponse:
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;text-align:center;padding-top:4rem'>"
        "<h1>Payment cancelled</h1>"
        "<p>No charge was made. Go back to your Claude conversation to try again.</p>"
        "</body></html>"
    )


@mcp.prompt
def user_journey() -> str:
    return (
        "You are an assistant for helping users find and purchase eSIM bundles from the Esim Hub service. "
        "Follow these steps to assist the user:\n"
        "1) Greet the user and ask him for what bundle he is looking for.\n"
        "2) Provide the user with available bundle options ( you can use the search_bundle tool).\n"
        "3) Ask the user to select a bundle by its code or index number (1,2,3).\n"
        "4) Ask the user for his email address to proceed with the purchase.\n"
        "5) Use the create_payment_link tool with the selected bundle code and the user's email, "
        "then share the payment URL with the user and ask him to complete the payment.\n"
        "6) After the user confirms he has paid, use the purchase_bundle_and_send_activation tool "
        "with the payment_session_id from step 5 to complete the purchase and email the activation details. "
        "If it reports the payment is not completed yet, ask the user to finish paying and try again.\n"
        "7) Confirm to the user that the activation details have been sent to his email.\n"
        "8) User can also ask for his order history by providing his email (use get_order_history tool).\n"
        "Always ensure to validate user inputs and handle errors gracefully. "
        "Never call purchase_bundle_and_send_activation without a paid payment session."
    )


@mcp.resource("resource://greeting")
def get_greeting() -> str:
    """Provides a simple greeting message."""
    return "Hello, welcome to the eSIM Hub! What bundle are you looking for today?"


@mcp.tool(
    name="get_all_bundles",
    description="Fetch all available eSIM bundles from the Esim Hub.",
    tags={"bundle", "esim", "esim hub"}
)
async def get_all_bundles(ctx: Context) -> List[Bundle]:
    """Fetch all bundles from the Esim Hub."""
    api_key = get_token(ctx=ctx)
    from config.utils import esim_hub_service_instance
    service = esim_hub_service_instance(api_key=api_key)
    bundles = await service.get_all_bundles()
    # Ensure JSON-serializable return:
    # If Bundle is Pydantic v2:
    return [b.model_dump() for b in bundles]


@mcp.tool(
    name="search_bundles",
    description="Search eSIM bundles from the Esim Hub based on various criteria.",
    tags={"bundle", "esim", "esim hub", "search"}
)
async def search_bundles(ctx: Context, keyword: str = None) -> List[Bundle]:
    """Search for bundles matching the given keyword and optional filters."""
    api_key = get_token(ctx=ctx)

    from config.utils import esim_hub_service_instance
    service = esim_hub_service_instance(api_key=api_key)
    return await service.search_bundles(search_keyword=keyword, country_name=None, gprs_from=None,
                                        gprs_to=None, currency_code=None, validity=None)


@mcp.tool(
    name="create_payment_link",
    description="Create a Stripe payment link for an eSIM bundle. The user must pay through this "
                "link before the bundle can be purchased with purchase_bundle_and_send_activation.",
    tags={"bundle", "esim", "payment", "stripe"}
)
async def create_payment_link(ctx: Context, bundle_code: str, user_email: str) -> dict:
    """Create a Stripe Checkout payment link for the given bundle, priced from the eSIM Hub."""
    api_key = get_token(ctx=ctx)

    from config.utils import esim_hub_service_instance
    from email_validator import validate_email, EmailNotValidError

    try:
        user_email = validate_email(user_email, check_deliverability=False).normalized
    except EmailNotValidError as e:
        return {"success": False, "error": f"Invalid email: {str(e)}"}

    service = esim_hub_service_instance(api_key=api_key)
    bundle = await service.get_bundle_by_code(bundle_code)
    if not bundle:
        return {"success": False, "error": f"Bundle {bundle_code} not found."}

    price = bundle.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        return {"success": False, "error": f"Bundle {bundle_code} has no valid price."}
    currency_code = (bundle.get("currency") or {}).get("currencyCode", "USD")
    bundle_name = (bundle.get("bundleDetails") or [{}])[0].get("name", bundle_code)

    try:
        checkout = await asyncio.to_thread(
            stripe_service.create_checkout_session,
            bundle_code, bundle_name, float(price), currency_code, user_email,
        )
    except Exception as e:
        logger.error(f"Failed to create checkout session for bundle {bundle_code}: {str(e)}")
        return {"success": False, "error": "Failed to create the payment link. Please try again."}

    return {
        "success": True,
        "payment_url": checkout["payment_url"],
        "payment_session_id": checkout["payment_session_id"],
        "amount": price,
        "currency": currency_code,
        "bundle_name": bundle_name,
        "instructions": "Share payment_url with the user. After they confirm they have paid, call "
                        "purchase_bundle_and_send_activation with this payment_session_id.",
    }


@mcp.tool(
    name="purchase_bundle_and_send_activation",
    description="Complete a PAID purchase: verifies the Stripe payment, creates the reseller order, "
                "and emails the activation details to the user. Requires the payment_session_id from "
                "create_payment_link, and the payment must already be completed by the user.",
    tags={"bundle", "esim", "purchase", "activation", "email"}
)
async def purchase_bundle_and_send_activation(ctx: Context, payment_session_id: str) -> dict:
    """Verify the Stripe payment, then purchase the bundle, fetch the activation code, and email it."""
    api_key = get_token(ctx=ctx)

    from config.utils import esim_hub_service_instance

    # 0) Verify the payment: the bundle and email come from the paid session's metadata,
    # so the order always matches what was actually paid for
    session = await asyncio.to_thread(stripe_service.get_session, payment_session_id)
    if session is None:
        return {"success": False, "error": f"Payment session {payment_session_id} not found."}
    if not stripe_service.is_paid(session):
        return {"success": False,
                "error": "Payment not completed yet. Ask the user to finish paying via the payment link, "
                         "then try again."}

    existing_order_id = await asyncio.to_thread(stripe_service.get_fulfilled_order_id, session)
    if existing_order_id:
        return {"success": False,
                "error": f"This payment was already used for order {existing_order_id}. "
                         "Create a new payment link for a new purchase."}

    bundle_code = stripe_service.metadata_value(session.metadata, "bundle_code")
    user_email = stripe_service.metadata_value(session.metadata, "user_email")
    if not bundle_code or not user_email:
        return {"success": False, "error": "Payment session is missing bundle/email metadata."}

    service = esim_hub_service_instance(api_key=api_key)

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

    # Tie the payment to the order immediately so this session can never fund a second order
    try:
        await asyncio.to_thread(stripe_service.mark_fulfilled, session, str(order_id))
    except Exception as e:
        logger.error(f"Failed to mark session {payment_session_id} fulfilled for order {order_id}: {str(e)}")

    # 2) Fetch activation code
    activation_code = await service.get_activation_code(order_id)
    if not activation_code:
        return {"success": False, "orderId": order_id,
                "error": f"Order {order_id} was created but retrieving the activation code failed. "
                         "Do not create a new payment; contact support with this order id."}

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
        "payment_session_id": payment_session_id,
        "user_email": user_email,
        "bundle_code": bundle_code,
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
async def get_order_history(ctx: Context, user_email: str) -> List[dict]:
    """Get order history for a given user email."""
    api_key = get_token(ctx=ctx)

    from config.utils import esim_hub_service_instance
    service = esim_hub_service_instance(api_key=api_key)
    return await service.get_order_history(user_email)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server_type", type=str, default="sse", choices=["sse", "stdio", "http", "stream"])
    # Default the port from environment for Render; fallback to 8181 locally
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 8181)))
    args = parser.parse_args()

    # Bind to all interfaces for Render
    mcp.run(transport=args.server_type, host="0.0.0.0", port=args.port)
