import hmac
import secrets
import time

from loguru import logger

OTP_TTL_SECONDS = 5 * 60
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN_SECONDS = 60

# email -> {"code": str, "expires_at": float, "attempts": int, "sent_at": float}
_pending_otps: dict[str, dict] = {}


def generate_otp(email: str) -> str | None:
    """Create and store a 6-digit OTP for the email.

    Returns None when a code was already sent within the resend cooldown.
    """
    email = email.strip().lower()
    now = time.monotonic()
    existing = _pending_otps.get(email)
    if existing and now - existing["sent_at"] < OTP_RESEND_COOLDOWN_SECONDS:
        logger.info(f"OTP resend throttled for {email}")
        return None
    code = f"{secrets.randbelow(1_000_000):06d}"
    _pending_otps[email] = {
        "code": code,
        "expires_at": now + OTP_TTL_SECONDS,
        "attempts": 0,
        "sent_at": now,
    }
    logger.info(f"generated OTP for {email}")
    return code


def verify_otp(email: str, code: str) -> bool:
    """Check the code for the email. The OTP is single-use and expires."""
    email = email.strip().lower()
    entry = _pending_otps.get(email)
    if entry is None:
        logger.info(f"OTP verify failed for {email}: no pending code")
        return False
    if time.monotonic() > entry["expires_at"]:
        del _pending_otps[email]
        logger.info(f"OTP verify failed for {email}: code expired")
        return False
    entry["attempts"] += 1
    if entry["attempts"] > OTP_MAX_ATTEMPTS:
        del _pending_otps[email]
        logger.info(f"OTP verify failed for {email}: too many attempts")
        return False
    if not hmac.compare_digest(entry["code"], code.strip()):
        logger.info(f"OTP verify failed for {email}: wrong code")
        return False
    del _pending_otps[email]
    logger.info(f"OTP verified for {email}")
    return True
