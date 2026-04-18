"""Notification for librarian handoff — supports Gmail SMTP and ntfy.sh push."""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx

logger = logging.getLogger(__name__)


def send_handoff_email(
    smtp_email: str,
    smtp_password: str,
    librarian_email: str,
    session_id: str,
    admin_url: str,
) -> bool:
    """Send an email notification via Gmail SMTP. Requires an App Password."""
    subject = "📚 A patron wants to talk to a librarian"
    body = (
        f"A patron has requested to speak with a librarian.\n\n"
        f"Session ID: {session_id}\n\n"
        f"Open the admin dashboard to respond:\n"
        f"{admin_url}/admin/\n\n"
        f"— Hero (Library Chatbot)"
    )

    msg = MIMEMultipart()
    msg["From"] = smtp_email
    msg["To"] = librarian_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
        logger.info("Handoff email sent for session %s", session_id)
        return True
    except Exception:
        logger.exception("Failed to send handoff email for session %s", session_id)
        return False


def send_ntfy_notification(
    ntfy_topic: str,
    session_id: str,
    admin_url: str,
) -> bool:
    """Send a push notification via ntfy.sh (free, no signup needed).

    The librarian subscribes to the topic at https://ntfy.sh/<topic>
    or via the ntfy app on their phone.
    """
    try:
        httpx.post(
            f"https://ntfy.sh/{ntfy_topic}",
            headers={
                "Title": "📚 Patron wants to talk to a librarian",
                "Click": f"{admin_url}/admin/",
                "Tags": "books,speech_balloon",
            },
            content=f"A patron is waiting for help.\nSession: {session_id}\nOpen the admin dashboard to respond.",
            timeout=10.0,
        )
        logger.info("ntfy notification sent for session %s", session_id)
        return True
    except Exception:
        logger.exception("Failed to send ntfy notification for session %s", session_id)
        return False
