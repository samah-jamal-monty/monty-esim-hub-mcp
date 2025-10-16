import os
from io import BytesIO

from dotenv import load_dotenv
from loguru import logger

from services.esim_hub_service import EsimHubService

load_dotenv()

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = os.getenv("SMTP_PORT", 587)
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "false").lower() in ("true", "1", "yes")

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
        logger.info(f"opening SMTP connection to {SMTP_SERVER}:{SMTP_PORT}")
        # Send email
        if SMTP_USE_TLS:
            with smtplib.SMTP_SSL(SMTP_SERVER, int(SMTP_PORT), timeout=10) as server:
                server.login(USERNAME, PASSWORD)
                server.send_message(msg)
                logger.info(f"Email sent successfully to {recipients}")
        else:
            with smtplib.SMTP(SMTP_SERVER, int(SMTP_PORT), timeout=10) as server:
                server.starttls()
                server.login(USERNAME, PASSWORD)
                server.send_message(msg)
                logger.info(f"Email sent successfully to {recipients}")
    except smtplib.SMTPException as e:
        logger.error(f"Failed to send email: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error while sending email: {str(e)}")
        raise
