"""Email notification service for AXXSPACE Phantom Unit System.

Sends transactional emails via Gmail SMTP for key platform events:
  - Password reset by admin
  - Units awarded (ledger update)
  - Chat room invitation
  - Task submission rejection

Configuration via environment variables:
  SMTP_USER     – your Gmail address (e.g. yourapp@gmail.com)
  SMTP_PASSWORD – Gmail App Password (NOT your normal Gmail password)
  EMAIL_FROM    – display name + address shown to recipients (optional)

Emails are sent in a background thread so they never block the HTTP response.
If SMTP credentials are not configured, emails are silently skipped.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)

# Log SMTP config on startup so Render logs confirm whether credentials loaded
def _log_smtp_config() -> None:
    if settings.smtp_user and settings.smtp_password:
        logger.warning(
            "[EMAIL] SMTP ready — user=%s port=%s ssl=%s",
            settings.smtp_user, settings.smtp_port, settings.smtp_use_ssl,
        )
    else:
        logger.warning(
            "[EMAIL] SMTP NOT configured — smtp_user=%r smtp_password_set=%s",
            settings.smtp_user, bool(settings.smtp_password),
        )

_log_smtp_config()

# ─────────────────────────────────────────────────────────────────────────────
# HTML email templates
# ─────────────────────────────────────────────────────────────────────────────

_BASE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{subject}</title>
<style>
  body {{ margin:0; padding:0; background:#0f0f1a; font-family:'Segoe UI',Arial,sans-serif; }}
  .wrapper {{ max-width:600px; margin:40px auto; background:#1a1a2e; border-radius:16px;
              overflow:hidden; box-shadow:0 8px 32px rgba(0,0,0,0.5); }}
  .header {{ background:linear-gradient(135deg,#6c63ff,#a855f7);
             padding:36px 32px; text-align:center; }}
  .header h1 {{ margin:0; font-size:22px; color:#fff; letter-spacing:0.5px; }}
  .header p {{ margin:6px 0 0; font-size:13px; color:rgba(255,255,255,0.75); }}
  .body {{ padding:36px 32px; color:#e2e8f0; }}
  .body h2 {{ margin:0 0 12px; font-size:20px; color:#a78bfa; }}
  .body p {{ margin:0 0 16px; font-size:15px; line-height:1.6; color:#cbd5e1; }}
  .highlight {{ background:#2d2d4e; border-left:4px solid #a855f7;
                padding:14px 18px; border-radius:8px; margin:20px 0; font-size:14px; }}
  .btn {{ display:inline-block; background:linear-gradient(135deg,#6c63ff,#a855f7);
          color:#fff; text-decoration:none; padding:14px 30px; border-radius:10px;
          font-size:15px; font-weight:600; margin:20px 0; }}
  .footer {{ background:#111122; padding:20px 32px; text-align:center;
             color:#4a5568; font-size:12px; }}
  .badge {{ display:inline-block; background:rgba(168,85,247,0.15);
            border:1px solid rgba(168,85,247,0.4); color:#a78bfa;
            padding:4px 12px; border-radius:99px; font-size:13px; font-weight:600; }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>⚡ AXXSPACE</h1>
    <p>Phantom Unit Compensation System</p>
  </div>
  <div class="body">
    {content}
  </div>
  <div class="footer">
    This is an automated notification from the AXXSPACE platform.<br/>
    Please do not reply to this email.
  </div>
</div>
</body>
</html>
"""


def _render(subject: str, content: str) -> str:
    return _BASE_HTML.format(subject=subject, content=content)


def _password_reset_html(name: str, new_password: str) -> str:
    content = f"""
    <h2>🔑 Password Reset</h2>
    <p>Hello <strong>{name}</strong>,</p>
    <p>An administrator has reset your AXXSPACE account password.</p>
    <div class="highlight">
      <strong>Your new temporary password:</strong><br/>
      <code style="font-size:18px;letter-spacing:2px;color:#a78bfa;">{new_password}</code>
    </div>
    <p>Please log in with this password and consider updating it with your admin if needed.</p>
    <p style="color:#94a3b8;font-size:13px;">If you did not expect this change, please contact your administrator immediately.</p>
    """
    return _render("Your password has been reset — AXXSPACE", content)


def _units_awarded_html(name: str, units: float, value_eur: float, task: str, reviewer: str) -> str:
    content = f"""
    <h2>🏆 Units Awarded!</h2>
    <p>Hello <strong>{name}</strong>,</p>
    <p>Great news — you've just received a new contribution unit award!</p>
    <div class="highlight">
      <span class="badge">+{units:g} Units</span>&nbsp;&nbsp;
      <span class="badge">€{value_eur:.2f} EUR</span>
      <p style="margin:10px 0 0;color:#94a3b8;font-size:13px;">
        <strong>Task:</strong> {task[:200]}{'…' if len(task) > 200 else ''}
      </p>
      <p style="margin:6px 0 0;color:#94a3b8;font-size:13px;">
        <strong>Reviewed by:</strong> {reviewer}
      </p>
    </div>
    <p>Log in to your dashboard to view your updated portfolio.</p>
    """
    return _render("You received new units — AXXSPACE", content)


def _chat_invite_html(name: str, room_name: str, invited_by: str) -> str:
    content = f"""
    <h2>💬 You've Been Invited to a Chat Room</h2>
    <p>Hello <strong>{name}</strong>,</p>
    <p><strong>{invited_by}</strong> has invited you to join a new conversation:</p>
    <div class="highlight">
      <strong>Room:</strong> {room_name}
    </div>
    <p>Log in to your AXXSPACE dashboard and open the Chat section to join the conversation.</p>
    """
    return _render(f"Chat invitation: {room_name} — AXXSPACE", content)


def _task_rejected_html(name: str, task_title: str, reason: str) -> str:
    content = f"""
    <h2>📋 Task Submission Update</h2>
    <p>Hello <strong>{name}</strong>,</p>
    <p>We have reviewed your task submission and unfortunately it was not approved at this time.</p>
    <div class="highlight">
      <strong>Task:</strong> {task_title}<br/>
      <strong>Reason:</strong> {reason}
    </div>
    <p>Please review the feedback, make any necessary adjustments, and feel free to resubmit.
       If you have questions, reach out via the AXXSPACE chat.</p>
    """
    return _render("Task submission update — AXXSPACE", content)


# ─────────────────────────────────────────────────────────────────────────────
# Core send function
# ─────────────────────────────────────────────────────────────────────────────

def _send(to_email: str, subject: str, html_body: str) -> None:
    """Internal: send one email synchronously."""
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("[EMAIL] SKIPPED (no credentials) subject=%r smtp_user=%r", subject, settings.smtp_user)
        return
    if not to_email:
        logger.warning("[EMAIL] SKIPPED (no recipient) subject=%r", subject)
        return

    logger.warning("[EMAIL] Attempting send → %s | %s", to_email, subject)

    from_addr = settings.email_from or f"AXXSPACE <{settings.smtp_user}>"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        if settings.smtp_use_ssl:
            # Port 465 — direct SSL (works on Render)
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_user, [to_email], msg.as_string())
        else:
            # Port 587 — STARTTLS (local dev)
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_user, [to_email], msg.as_string())
        logger.warning("[EMAIL] SUCCESS → %s | %s", to_email, subject)
    except Exception as exc:
        logger.exception("[EMAIL] FAILED → %s | error: %s", to_email, exc)


def _send_async(to_email: str, subject: str, html_body: str) -> None:
    """Send email synchronously.

    Previously used a background thread but Render's free tier kills threads
    before they complete. Running synchronously guarantees delivery.
    """
    _send(to_email, subject, html_body)


def send_test_email(to_email: str) -> dict:
    """Send a test email synchronously and return a result dict."""
    if not settings.smtp_user or not settings.smtp_password:
        return {"ok": False, "error": "SMTP credentials not configured (SMTP_USER / SMTP_PASSWORD missing)."}
    subject = "✅ AXXSPACE — Test Email"
    html = _render(subject, """
    <h2>✅ Email is working!</h2>
    <p>This is a test email from the AXXSPACE platform.</p>
    <p>If you received this, your Gmail SMTP configuration is correct.</p>
    """)
    from_addr = settings.email_from or f"AXXSPACE <{settings.smtp_user}>"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))
    try:
        if settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_user, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_user, [to_email], msg.as_string())
        logger.info("Test email sent → %s", to_email)
        return {"ok": True, "message": f"Test email sent to {to_email}"}
    except smtplib.SMTPAuthenticationError as e:
        return {"ok": False, "error": f"Gmail authentication failed — check App Password. Detail: {e}"}
    except smtplib.SMTPException as e:
        return {"ok": False, "error": f"SMTP error: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"Unexpected error: {e}"}


# ─────────────────────────────────────────────────────────────────────────────
# Public API — one function per notification type
# ─────────────────────────────────────────────────────────────────────────────

def send_password_reset(to_email: str, name: str, new_password: str) -> None:
    """Notify a member/investor that their password was reset by an admin."""
    _send(
        to_email,
        "Your AXXSPACE password has been reset",
        _password_reset_html(name, new_password),
    )


def send_units_awarded(
    to_email: str,
    name: str,
    units: float,
    value_eur: float,
    task: str,
    reviewer: str,
) -> None:
    """Notify a member that the admin awarded them contribution units."""
    _send(
        to_email,
        f"🏆 You received {units:g} units — AXXSPACE",
        _units_awarded_html(name, units, value_eur, task, reviewer),
    )


def send_chat_invite(
    to_email: str, name: str, room_name: str, invited_by: str
) -> None:
    """Notify a member that they've been invited to a chat room."""
    _send(
        to_email,
        f"💬 You're invited to '{room_name}' — AXXSPACE",
        _chat_invite_html(name, room_name, invited_by),
    )


def send_task_rejected(
    to_email: str, name: str, task_title: str, reason: str
) -> None:
    """Notify a member that their task submission was rejected."""
    _send(
        to_email,
        "📋 Task submission update — AXXSPACE",
        _task_rejected_html(name, task_title, reason),
    )
