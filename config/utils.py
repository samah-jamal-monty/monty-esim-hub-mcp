import os
from io import BytesIO

import qrcode
from dotenv import load_dotenv
from loguru import logger

from services.esim_hub_service import EsimHubService

load_dotenv()

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = os.getenv("SMTP_PORT", 587)
# Keep backward-compatible env name SMTP_USE_TLS but interpret it as "prefer SSL (SMTP_SSL)"
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "false").lower() in ("true", "1", "yes")
# Allow configuring timeout
SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", 10))

USERNAME = os.getenv("SMTP_USERNAME", "<EMAIL>")
PASSWORD = os.getenv("SMTP_PASSWORD", "<PASSWORD>")


def esim_hub_service_instance() -> EsimHubService:
    return EsimHubService(
        digital_service_url=os.getenv("ESIM_DIGITAL_SERVICE_URL"),
        mm_hub_url=os.getenv("ESIM_MM_HUB_API_URL"),
        api_key=os.getenv("ESIM_HUB_API_KEY"),
        tenant_key=os.getenv("ESIM_HUB_TENANT_KEY")
    )


def send_email(subject: str, html_content: str, recipients: str, attachment: BytesIO = None):
    """
    Send an email with optional attachment.

    Args:
        subject (str): Email subject
        html_content (str): HTML content of the email
        recipients (str): Comma-separated list of recipient email addresses
        attachment (BytesIO, optional): Optional attachment to include in the email

    Raises:
        ValueError: If required email configuration is missing
        smtplib.SMTPException: If there's an error sending the email
    """
    if not all([SMTP_SERVER, SMTP_PORT, USERNAME, PASSWORD]):
        raise ValueError("Missing required email configuration")

    import smtplib
    from email.utils import formatdate, formataddr
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email import encoders

    try:
        # Create message
        msg = MIMEMultipart('mixed')  # Use 'mixed' for attachments
        msg['Subject'] = subject
        sender_email = os.getenv("SMTP_SENDER", "noreply@esim.com")
        sender_name = os.getenv("SMTP_SENDER_NAME", "Esim Support")
        msg['From'] = formataddr((sender_name, sender_email))
        msg['To'] = recipients
        msg['Date'] = formatdate(localtime=True)

        # Add text and HTML content as a subpart
        alt_part = MIMEMultipart('alternative')
        text_content = "Please view this email in an HTML-compatible email client."
        alt_part.attach(MIMEText(text_content, 'plain'))
        alt_part.attach(MIMEText(html_content, 'html'))
        msg.attach(alt_part)

        # Add attachment if provided
        if attachment:
            attachment.seek(0)
            img = MIMEBase('image', 'png')
            img.set_payload(attachment.read())
            encoders.encode_base64(img)
            img.add_header('Content-Disposition', 'attachment', filename='qr_code.png')
            msg.attach(img)

        # Prepare connection params
        try:
            port = int(SMTP_PORT)
        except Exception:
            port = 587
        timeout = int(os.getenv("SMTP_TIMEOUT", SMTP_TIMEOUT))

        # If the configured port is 587 (STARTTLS), many providers expect implicit SSL on 465.
        # Prefer using 465 for SMTP_SSL attempts when port == 587 to avoid connecting with SSL on 587 which may time out.
        ssl_port = port if port != 587 else 465

        logger.info(
            f"opening SMTP connection to {SMTP_SERVER}:{port} (timeout={timeout}s), prefer_ssl={SMTP_USE_TLS}, smtp_ssl_port={ssl_port}"
        )

        # Define concrete send actions that raise on failure
        def _send_via_smtp_ssl(target_port: int):
            logger.info(f"Attempting SMTP_SSL connection to {SMTP_SERVER}:{target_port}")
            with smtplib.SMTP_SSL(SMTP_SERVER, target_port, timeout=timeout) as server:
                server.login(USERNAME, PASSWORD)
                server.send_message(msg)

        def _send_via_smtp_starttls(target_port: int):
            logger.info(f"Attempting SMTP connection with STARTTLS to {SMTP_SERVER}:{target_port}")
            with smtplib.SMTP(SMTP_SERVER, target_port, timeout=timeout) as server:
                server.ehlo()
                try:
                    server.starttls()
                    server.ehlo()
                except Exception as e:
                    # STARTTLS may not be supported; log and continue to attempt login without it
                    logger.warning(f"STARTTLS failed or not supported: {e}")
                server.login(USERNAME, PASSWORD)
                server.send_message(msg)

        # Build attempt list (name, callable) in the preferred order
        if SMTP_USE_TLS:
            attempts = [
                (f"SMTP_SSL:{ssl_port}", lambda: _send_via_smtp_ssl(ssl_port)),
                (f"SMTP+STARTTLS:{port}", lambda: _send_via_smtp_starttls(port)),
            ]
        else:
            attempts = [
                (f"SMTP+STARTTLS:{port}", lambda: _send_via_smtp_starttls(port)),
                (f"SMTP_SSL:{ssl_port}", lambda: _send_via_smtp_ssl(ssl_port)),
            ]

        last_exc = None
        # Try each attempt in order; return on first success
        for name, fn in attempts:
            try:
                fn()
                logger.info(f"Email sent successfully to {recipients} via {name}")
                return
            except Exception as e:
                last_exc = e
                logger.warning(f"{name} send failed: {e}")

        # If we reach here all attempts failed
        logger.exception("All SMTP send strategies failed")
        if last_exc:
            raise last_exc
        else:
            raise RuntimeError("Failed to send email: unknown error")

    except smtplib.SMTPException as e:
        logger.exception(f"Failed to send email: {str(e)}")
        raise
    except Exception as e:
        # Log full exception including stack trace to help diagnose timeouts
        logger.exception(f"Unexpected error while sending email: {str(e)}")
        raise


def generate_qr_code(qr_data: str) -> BytesIO:
    qr = qrcode.make(qr_data)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
