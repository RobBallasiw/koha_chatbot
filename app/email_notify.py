"""Notification for librarian handoff — supports Gmail service account, SMTP, and ntfy.sh."""

import base64
import json
import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gmail API via service account (domain-wide delegation)
# ---------------------------------------------------------------------------

_gmail_service = None


def _get_gmail_service():
    """Build and cache a Gmail API service using a service account."""
    global _gmail_service
    if _gmail_service is not None:
        return _gmail_service

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    creds_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    delegate_email = os.environ.get("SMTP_EMAIL", "")

    if not delegate_email:
        return None

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

        if creds_json:
            info = json.loads(creds_json)
            credentials = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        elif creds_file and os.path.exists(creds_file):
            credentials = service_account.Credentials.from_service_account_file(creds_file, scopes=SCOPES)
        else:
            return None

        # Delegate to the actual sender email (must be in the same Google Workspace)
        delegated = credentials.with_subject(delegate_email)
        _gmail_service = build("gmail", "v1", credentials=delegated, cache_discovery=False)
        logger.info("Gmail API service account initialised (delegating to %s)", delegate_email)
        return _gmail_service
    except Exception:
        logger.exception("Failed to initialise Gmail service account")
        return None


def _use_service_account() -> bool:
    """Check if service account credentials are configured."""
    return bool(
        os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        or os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    )


def _send_via_service_account(msg: MIMEMultipart) -> bool:
    """Send an email using the Gmail API with service account credentials."""
    service = _get_gmail_service()
    if service is None:
        return False
    try:
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        return True
    except Exception:
        logger.exception("Failed to send email via Gmail API service account")
        return False


def _send_via_smtp(smtp_email: str, smtp_password: str, msg: MIMEMultipart) -> bool:
    """Send an email using Gmail SMTP with app password."""
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
        return True
    except Exception:
        logger.exception("Failed to send email via SMTP")
        return False


def _send_email(smtp_email: str, smtp_password: str, msg: MIMEMultipart) -> bool:
    """Send email — tries service account first, falls back to SMTP."""
    if _use_service_account():
        ok = _send_via_service_account(msg)
        if ok:
            return True
        logger.warning("Service account failed, falling back to SMTP")
    if smtp_email and smtp_password:
        return _send_via_smtp(smtp_email, smtp_password, msg)
    logger.warning("No email credentials configured (neither service account nor SMTP)")
    return False


def _build_chat_link(admin_url: str, session_id: str = "", staff_name: str = "") -> str:
    """Build a /chat/ link with embedded API key and optional params."""
    api_key = os.environ.get("ADMIN_API_KEY", "")
    parts = [f"{admin_url}/chat/?key={api_key}"]
    if session_id:
        parts.append(f"session={session_id}")
    if staff_name:
        from urllib.parse import quote
        parts.append(f"name={quote(staff_name)}")
    return "&".join(parts)


# ---------------------------------------------------------------------------
# Email builders
# ---------------------------------------------------------------------------

def send_handoff_email(
    smtp_email: str,
    smtp_password: str,
    librarian_email: str,
    session_id: str,
    admin_url: str,
) -> bool:
    """Send a handoff notification email."""
    chat_link = _build_chat_link(admin_url, session_id=session_id)
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

    sender = smtp_email or os.environ.get("SMTP_EMAIL", "noreply@example.com")
    msg = MIMEMultipart("alternative")
    msg["From"] = f"Lorma Library Chatbot <{sender}>"
    msg["To"] = librarian_email
    msg["Subject"] = subject
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    ok = _send_email(smtp_email, smtp_password, msg)
    if ok:
        logger.info("Handoff email sent for session %s", session_id)
    return ok


def send_staff_notify_email(
    smtp_email: str,
    smtp_password: str,
    recipient_email: str,
    staff_name: str,
    session_id: str,
    admin_url: str,
) -> bool:
    """Send a personalized notification email to a specific librarian."""
    chat_link = _build_chat_link(admin_url, session_id=session_id, staff_name=staff_name)
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

    plain_body = f"Hi {staff_name},\n\nA patron is waiting to chat with a librarian.\n"
    if session_id:
        plain_body += f"Session: {session_id[:16]}…\n"
    plain_body += f"\nJoin the live chat:\n{chat_link}\n\n— Lorma Library Chatbot"

    sender = smtp_email or os.environ.get("SMTP_EMAIL", "noreply@example.com")
    msg = MIMEMultipart("alternative")
    msg["From"] = f"Lorma Library Chatbot <{sender}>"
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    ok = _send_email(smtp_email, smtp_password, msg)
    if ok:
        logger.info("Staff notification sent to %s (%s)", staff_name, recipient_email)
    return ok


def send_ntfy_notification(
    ntfy_topic: str,
    session_id: str,
    admin_url: str,
) -> bool:
    """Send a push notification via ntfy.sh."""
    chat_link = _build_chat_link(admin_url, session_id=session_id)
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
