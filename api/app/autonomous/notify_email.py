"""Best-effort SMTP email transport for autonomous notifications — M4-C1.

The ``notify`` chokepoint handler writes a durable in-app
:class:`~app.models.autonomous.AutonomousNotification` row (the record of
truth) and then calls :func:`send_notification_email` as a **best-effort**
transport. Email is a convenience copy of the in-app notification — never
the durable record — so this module is deliberately fault-tolerant:

* **Clean no-op when unconfigured.** With ``smtp_host`` unset (or no
  recipient address) it returns ``False`` without raising and logs at
  debug. Operators who never set SMTP get working in-app notifications
  with zero email noise.
* **Never raises.** Any transport / auth / parse failure is caught,
  logged at warning (``event="autonomous_notify_email_failed"``), and
  surfaced as a ``False`` return. A failed send must never break the
  autonomous session.

No new dependency (CLAUDE.md SBOM posture): the send uses stdlib
``smtplib`` + :class:`email.message.EmailMessage`, run off the event loop
via :func:`asyncio.to_thread` so the blocking socket I/O does not stall
the arq worker's event loop.

The ``subject`` / ``body`` carry only what the ``notify`` ``params``
carried — counts / IDs / a receipt link — never raw entity values. This
module does not add content; it transports what it is given.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

log = logging.getLogger(__name__)


def _send_sync(
    *,
    host: str,
    port: int,
    use_tls: bool,
    username: str | None,
    password: str | None,
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    timeout: int,
) -> None:
    """Blocking SMTP send — runs in a worker thread via ``asyncio.to_thread``.

    Builds a plain-text :class:`EmailMessage`, connects, optionally issues
    STARTTLS, optionally logs in, and sends. The ``timeout`` bounds connect
    AND subsequent socket ops (STARTTLS / send) so a hung mail server can't
    tie up the worker thread indefinitely. Raises on any failure (including
    a :class:`TimeoutError`); the async wrapper catches and logs.
    """
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=timeout) as smtp:
        if use_tls:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(msg)


async def send_notification_email(
    *,
    to_addr: str | None,
    subject: str,
    body: str,
) -> bool:
    """Best-effort send of an autonomous notification by email.

    Returns ``True`` only on a successful send. Returns ``False`` — never
    raises — when SMTP is unconfigured, the recipient is missing, or the
    send fails for any reason.

    Args:
        to_addr: The recipient address (the session user's email). A
            falsy value short-circuits to a ``False`` no-op.
        subject: Email subject — the notification ``title``.
        body: Email body — the notification ``body`` (counts / IDs /
            receipt link; never raw entity values).

    Returns:
        ``True`` if the email was sent; ``False`` for an unconfigured /
        skipped / failed send.
    """
    settings = get_settings()

    # Clean no-op: email disabled (no host) or no recipient.
    if not settings.smtp_host or not to_addr:
        log.debug(
            "autonomous_notify_email_skipped",
            extra={
                "event": "autonomous_notify_email_skipped",
                "configured": bool(settings.smtp_host),
                "has_recipient": bool(to_addr),
            },
        )
        return False

    from_addr = settings.smtp_from or settings.smtp_username
    if not from_addr:
        # No usable From address — treat as unconfigured rather than guess.
        log.debug(
            "autonomous_notify_email_skipped",
            extra={"event": "autonomous_notify_email_skipped", "reason": "no_from_addr"},
        )
        return False

    try:
        await asyncio.to_thread(
            _send_sync,
            host=settings.smtp_host,
            port=settings.smtp_port,
            use_tls=settings.smtp_use_tls,
            username=settings.smtp_username,
            password=settings.smtp_password,
            from_addr=from_addr,
            to_addr=to_addr,
            subject=subject,
            body=body,
            timeout=settings.smtp_timeout,
        )
    except Exception:
        # Best-effort: a transport/auth/parse failure must NEVER propagate.
        log.warning(
            "autonomous_notify_email_failed",
            extra={"event": "autonomous_notify_email_failed"},
            exc_info=True,
        )
        return False

    return True
