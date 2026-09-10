"""Light-queue tasks: outbound email.

No database access - the caller (app/api/v1/auth.py) passes everything an
email needs (address, display name, a ready-to-click link) as task arguments,
so sending mail never waits on a DB round trip and stays genuinely light:
sharing worker infrastructure with a heavy AI task should never make a
verification email slower to send.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.core.celery_app import celery_app
from app.core.config import get_settings


def _send(to_email: str, subject: str, body: str) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST is not configured; cannot send email.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_email
    message["To"] = to_email
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
        if settings.smtp_use_tls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password or "")
        client.send_message(message)


@celery_app.task(
    name="app.tasks.email.send_verification_email",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def send_verification_email(
    self, to_email: str, display_name: str | None, verify_url: str
) -> None:
    greeting = f"Hi {display_name}," if display_name else "Hi,"
    body = (
        f"{greeting}\n\n"
        "Welcome to MoodVerse. Confirm your email address to finish setting up "
        "your account:\n\n"
        f"{verify_url}\n\n"
        f"This link expires in {get_settings().email_verification_token_expire_hours} hours.\n\n"
        "If you did not create this account, you can safely ignore this email."
    )
    try:
        _send(to_email, "Verify your MoodVerse email", body)
    except Exception as exc:
        raise self.retry(exc=exc) from exc
