import argparse
from typing import List

from fastapi import FastAPI
from fastmcp import FastMCP

from config.utils import send_email
from dto.bundle import Bundle

mcp = FastMCP("Esim Hub Management API")
api = FastAPI()


@api.get("/")
def health():
    return {"status": "ok"}


# Mount MCP HTTP transport on /mcp instead of /
api.mount("/mcp", mcp.http_app())
app = api


@mcp.prompt
def system_message() -> str:
    return (
        "You are a helpful assistant that provides information about eSIM bundles and helps users purchase them. "
        "Use the available tools to fetch bundle details, create orders, retrieve activation codes, and send activation URLs via email. "
        "Always ensure to collect a valid email address from the user before proceeding with order creation."
    )


@mcp.prompt
def user_journey() -> str:
    return (
        "The typical user journey is as follows:\n"
        "1) User asks about available eSIM bundles.\n"
        "2) Use the 'get_all_bundles' tool to fetch and display available bundles.\n"
        "3) User selects a bundle and provides a valid email address (required for order).\n"
        "4) Create the order and deliver activation details:\n"
        "   - Option A (recommended, one call): use 'purchase_bundle_and_send_activation(user_email, bundle_code)'. It will:\n"
        "     • Create the reseller order including the user's email.\n"
        "     • Extract 'smdpAdress' (SMDP+ address) and 'orderId' from the order response.\n"
        "     • Call 'get_activation_code(orderId)' to obtain the activation code.\n"
        "     • Build the activation URL in the form: LPA:1$<SMDP+>$<ACTIVATION_CODE>.\n"
        "     • Email the activation details (SMDP+ address, activation code, activation URL) to the user.\n"
        "   - Option B (manual steps):\n"
        "     • Call 'purchase_bundle(user_email, bundle_code)' to create the order.\n"
        "     • From the response, extract 'orderId' and 'smdpAdress'.\n"
        "     • Call 'get_activation_code(orderId)' to get the activation code.\n"
        "     • Construct 'activation_url' = LPA:1$<SMDP+>$<ACTIVATION_CODE>.\n"
        "     • Call 'send_activation_url_via_email(user_email, activation_url)'.\n"
        "5) Confirm to the user that the activation details have been emailed (provide a brief summary without exposing sensitive data).\n"
        "Always validate the email format before using it."
    )


@mcp.tool
def test() -> dict:
    return {"message": "The API is working!"}


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
async def purchase_bundle(user_email: str, bundle_code: str) -> dict:
    """Purchase a bundle by its code. Returns True if successful. User email is required for the order."""
    from config.utils import esim_hub_service_instance
    from email_validator import validate_email, EmailNotValidError

    # Basic validation to ensure the agent captured a valid email
    try:
        user_email = validate_email(user_email, check_deliverability=False).normalized
    except EmailNotValidError as e:
        return {"success": False, "error": f"Invalid email: {str(e)}"}

    service = esim_hub_service_instance()
    return await service.purchase_bundle(bundle_code, user_email)


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

    # Email the activation URL; return success/failure
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
        send_email(subject=subject, html_content=body, recipients=user_email)
        emailed = True
    except Exception as e:
        emailed = False

    return {
        "success": True,
        "orderId": order_id,
        "smdp_address": smdp_address,
        "activation_code": activation_code,
        "activation_url": activation_url,
        "email_sent": emailed,
    }


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
        send_email(subject=subject, html_content=body, recipients=user_email)
        return True
    except Exception:
        return False


@mcp.tool
async def get_activation_code(order_id: str) -> str:
    """Get activation code for a given order GUID."""
    from config.utils import esim_hub_service_instance
    service = esim_hub_service_instance()
    return await service.get_activation_code(order_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server_type", type=str, default="sse", choices=["sse", "stdio"])
    parser.add_argument("--port", type=int, default=8181)
    args = parser.parse_args()
    mcp.run(transport=args.server_type, port=args.port)
