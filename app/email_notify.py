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
    chat_link = f"{admin_url}/admin/#handoff-tab"
    subject = "📚 A patron wants to talk to a librarian"

    html_body = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:480px;margin:0 auto;padding:20px">
      <div style="background:#2c3e50;color:#fff;padding:16px 20px;border-radius:8px 8px 0 0;text-align:center">
        <h2 style="margin:0;font-size:1.1rem">📚 Librarian Needed</h2>
      </div>
      <div style="background:#fff;border:1px solid #ecf0f1;border-top:none;padding:24px 20px;border-radius:0 0 8px 8px">
        <p style="color:#333;font-size:0.95rem;margin:0 0 16px">A patron is waiting to chat with a librarian.</p>
        <p style="color:#7f8c8d;font-size:0.85rem;margin:0 0 20px">Session: {session_id[:16]}…</p>
        <div style="text-align:center;margin:20px 0">
          <a href="{chat_link}" style="display:inline-block;background:#2c3e50;color:#fff;text-decoration:none;padding:12px 28px;border-radius:6px;font-size:0.95rem;font-weight:600">
            💬 Join Live Chat
          </a>
        </div>
        <p style="color:#bdc3c7;font-size:0.78rem;text-align:center;margin:16px 0 0">— Lorma Library Chatbot</p>
      </div>
    </div>
    """

    plain_body = (
        f"A patron has requested to speak with a librarian.\n\n"
        f"Session: {session_id[:16]}…\n\n"
        f"Join the live chat:\n{chat_link}\n\n"
        f"— Lorma Library Chatbot"
    )

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Lorma Library Chatbot <{smtp_email}>"
    msg["To"] = librarian_email
    msg["Subject"] = subject
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

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


def send_staff_notify_email(
    smtp_email: str,
    smtp_password: str,
    recipient_email: str,
    staff_name: str,
    session_id: str,
    admin_url: str,
) -> bool:
    """Send a targeted notification email to a specific librarian."""
    chat_link = f"{admin_url}/admin/#handoff-tab"
    subject = f"📚 {staff_name}, a patron needs your help"

    session_note = ""
    if session_id:
        session_note = f'<p style="color:#7f8c8d;font-size:0.85rem;margin:0 0 20px">Session: {session_id[:16]}…</p>'

    html_body = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:480px;margin:0 auto;padding:20px">
      <div style="background:#2c3e50;color:#fff;padding:16px 20px;border-radius:8px 8px 0 0;text-align:center">
        <h2 style="margin:0;font-size:1.1rem">📚 Librarian Needed</h2>
      </div>
      <div style="background:#fff;border:1px solid #ecf0f1;border-top:none;padding:24px 20px;border-radius:0 0 8px 8px">
        <p style="color:#333;font-size:0.95rem;margin:0 0 16px">Hi <strong>{staff_name}</strong>, a patron is waiting to chat with a librarian. Please join the live chat when you're available.</p>
        {session_note}
        <div style="text-align:center;margin:20px 0">
          <a href="{chat_link}" style="display:inline-block;background:#2c3e50;color:#fff;text-decoration:none;padding:12px 28px;border-radius:6px;font-size:0.95rem;font-weight:600">
            💬 Join Live Chat
          </a>
        </div>
        <p style="color:#bdc3c7;font-size:0.78rem;text-align:center;margin:16px 0 0">— Lorma Library Chatbot</p>
      </div>
    </div>
    """

    plain_body = (
        f"Hi {staff_name},\n\n"
        f"A patron is waiting to chat with a librarian.\n"
    )
    if session_id:
        plain_body += f"Session: {session_id[:16]}…\n"
    plain_body += (
        f"\nJoin the live chat:\n{chat_link}\n\n"
        f"— Lorma Library Chatbot"
    )

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Lorma Library Chatbot <{smtp_email}>"
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
        logger.info("Staff notification sent to %s (%s)", staff_name, recipient_email)
        return True
    except Exception:
        logger.exception("Failed to send staff notification to %s", recipient_email)
        return False


def send_ntfy_notification(
    ntfy_topic: str,
    session_id: str,
    admin_url: str,
) -> bool:
    """Send a push notification via ntfy.sh."""
    chat_link = f"{admin_url}/admin/#handoff-tab"
    try:
        httpx.post(
            f"https://ntfy.sh/{ntfy_topic}",
            headers={
                "Title": "📚 Patron wants to talk to a librarian",
                "Click": chat_link,
                "Tags": "books,speech_balloon",
            },
            content=f"A patron is waiting for help.\nSession: {session_id[:16]}…\nTap to join the live chat.",
            timeout=10.0,
        )
        logger.info("ntfy notification sent for session %s", session_id)
        return True
    except Exception:
        logger.exception("Failed to send ntfy notification for session %s", session_id)
        return False
