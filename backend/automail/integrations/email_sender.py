"""SMTP email sender utility for transactional emails (e.g. verification)."""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from automail.core.brand import get_brand

logger = logging.getLogger(__name__)


def _smtp_config() -> tuple[str, int, str, str, str]:
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)
    return smtp_host, smtp_port, smtp_user, smtp_password, smtp_from


def _send_email(to_email: str, subject: str, text_body: str, html_body: str) -> None:
    smtp_host, smtp_port, smtp_user, smtp_password, smtp_from = _smtp_config()
    if not smtp_host:
        logger.warning("SMTP_HOST not configured — skipping email for %s", to_email)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        if smtp_user and smtp_password:
            server.login(smtp_user, smtp_password)
        server.sendmail(smtp_from, to_email, msg.as_string())


def send_login_code_email(to_email: str, code: str) -> None:
    """Send a short login code to the given address."""
    brand = get_brand()
    subject = f"Your {brand.name} login code"
    text_body = (
        f"Your {brand.name} login code is:\n\n"
        f"{code}\n\n"
        "The code expires in 10 minutes. If you did not request this code, you can ignore this email."
    )
    html_body = f"""\
<html>
  <body>
    <h2>Your {brand.name} login code</h2>
    <p>Use this code to sign in:</p>
    <p style="font-size: 24px; font-weight: 700; letter-spacing: 4px;"><code>{code}</code></p>
    <p>The code expires in 10 minutes.</p>
    <p>If you did not request this code, you can safely ignore this email.</p>
  </body>
</html>"""
    _send_email(to_email, subject, text_body, html_body)
    logger.info("Login code email sent to %s", to_email)


def send_verification_email(to_email: str, token: str) -> None:
    """Send an email-verification link to the given address.

    Reads SMTP configuration from environment variables:
        SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD,
        SMTP_FROM (defaults to SMTP_USER), APP_BASE_URL.

    If SMTP_HOST is not set the function logs a warning and returns without
    sending — useful in dev mode where SMTP is not configured.
    """
    app_base_url = os.getenv("APP_BASE_URL", "http://localhost:5174").rstrip("/")

    verify_url = f"{app_base_url}/verify-email?token={token}"

    brand = get_brand()

    subject = f"Verify your {brand.name} account"
    text_body = (
        f"Welcome to {brand.name}!\n\n"
        "Please verify your email address by clicking the link below:\n\n"
        f"{verify_url}\n\n"
        f"If you did not sign up for {brand.name}, you can ignore this email."
    )
    html_body = f"""\
<html>
  <body>
    <h2>Welcome to {brand.name}!</h2>
    <p>Please verify your email address by clicking the link below:</p>
    <p><a href="{verify_url}">Verify my email address</a></p>
    <p>Or copy this URL into your browser:<br>
       <code>{verify_url}</code></p>
    <p>If you did not sign up for {brand.name}, you can safely ignore this email.</p>
  </body>
</html>"""

    try:
        _send_email(to_email, subject, text_body, html_body)
        logger.info("Verification email sent to %s", to_email)
    except Exception:
        logger.exception("Failed to send verification email to %s", to_email)
        raise
