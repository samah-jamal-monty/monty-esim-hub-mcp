"""Stripe Checkout integration for collecting payment before creating a reseller order.

Flow: create a Checkout Session for the bundle's server-side price, send the user the
session URL to pay, then verify payment_status == "paid" before fulfilling. After
fulfillment the eSIM order id is stamped on the PaymentIntent metadata so a session can
never be fulfilled twice, even across server restarts.

All functions are synchronous (the stripe SDK is sync); call them from async tools via
asyncio.to_thread.
"""

import os

import stripe
from loguru import logger

FULFILLED_METADATA_KEY = "esim_order_id"


def metadata_value(metadata, key: str) -> str | None:
    """Safe metadata lookup: StripeObject is not a dict — it only supports [] and `in`."""
    if metadata is None:
        return None
    return metadata[key] if key in metadata else None


def _init() -> None:
    stripe.api_key = os.environ["STRIPE_SK_KEY"]


def _base_url() -> str:
    return os.getenv("MCP_BASE_URL", "https://esim-hub-mcp.onrender.com").rstrip("/")


def create_checkout_session(bundle_code: str, bundle_name: str, amount: float,
                            currency_code: str, user_email: str) -> dict:
    """Create a Checkout Session for one bundle and return its payment URL and id."""
    _init()
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": currency_code.lower(),
                "unit_amount": int(round(amount * 100)),
                "product_data": {"name": f"eSIM bundle: {bundle_name}"},
            },
            "quantity": 1,
        }],
        customer_email=user_email,
        metadata={"bundle_code": bundle_code, "user_email": user_email},
        success_url=f"{_base_url()}/payment/success",
        cancel_url=f"{_base_url()}/payment/cancel",
    )
    logger.info(f"created checkout session {session.id} for bundle {bundle_code} ({amount} {currency_code})")
    return {"payment_session_id": session.id, "payment_url": session.url}


def parse_webhook_event(payload: bytes, signature_header: str) -> stripe.Event:
    """Verify the Stripe-Signature header and return the event. Raises on bad signature."""
    return stripe.Webhook.construct_event(payload, signature_header, os.environ["STRIPE_WEBHOOK_KEY"])


def get_session(session_id: str) -> stripe.checkout.Session | None:
    _init()
    try:
        return stripe.checkout.Session.retrieve(session_id)
    except stripe.InvalidRequestError:
        logger.error(f"checkout session {session_id} not found")
        return None


def is_paid(session: stripe.checkout.Session) -> bool:
    return session.payment_status == "paid"


def get_fulfilled_order_id(session: stripe.checkout.Session) -> str | None:
    """Return the eSIM order id if this session was already fulfilled."""
    if not session.payment_intent:
        return None
    _init()
    payment_intent = stripe.PaymentIntent.retrieve(session.payment_intent)
    return metadata_value(payment_intent.metadata, FULFILLED_METADATA_KEY)


def mark_fulfilled(session: stripe.checkout.Session, order_id: str) -> None:
    """Stamp the eSIM order id on the PaymentIntent so the session can't be fulfilled twice."""
    if not session.payment_intent:
        logger.error(f"session {session.id} has no payment_intent to mark fulfilled")
        return
    _init()
    stripe.PaymentIntent.modify(session.payment_intent, metadata={FULFILLED_METADATA_KEY: order_id})
    logger.info(f"marked session {session.id} fulfilled with order {order_id}")
