"""Web Push notification support for Planner OS.

Uses the Web Push protocol (VAPID) to send native notifications to
macOS, iOS, iPadOS, and any browser that supports the Push API.

Required env vars:
  VAPID_PRIVATE_KEY  — base64url-encoded EC P-256 private key
  VAPID_PUBLIC_KEY   — base64url-encoded EC P-256 public key (sent to the browser)
  VAPID_MAILTO       — contact email, e.g. mailto:you@example.com

Generate a key pair once with:
  python -c "from planner_core.push import generate_vapid_keys; print(generate_vapid_keys())"
"""

from __future__ import annotations

import json
import logging
import os
import re
from urllib.parse import urlsplit
from typing import Any

logger = logging.getLogger(__name__)

# How long to wait on a push service before giving up on one subscription.
#
# This has to be passed explicitly, and leaving it off is not a smaller
# version of the same behaviour — it is unbounded. pywebpush's send() reads
# kwargs.pop("timeout", 10000), but webpush() always forwards timeout whether
# you set it or not, so the key is present as None and the 10000 default never
# applies. requests.post(timeout=None) then waits for ever.
#
# A push endpoint that accepts the connection and never answers therefore
# holds its thread permanently. The reminder cron runs every five minutes and
# sends to every subscription, so each run leaks another thread; Cloud Run
# returning 504 at its 300s request limit does not release it, because the
# thread is still inside requests. Once the threadpool was gone every
# synchronous route went with it — /api/health included, which does no I/O at
# all — while async MCP traffic carried on being served off the event loop and
# made the service look alive. Nothing recovers this but a restart, and the
# next cron starts it again.
#
# A subscription that hangs also never returns the 404 or 410 that would have
# retired it, so it comes back on every run.
PUSH_TIMEOUT_SECONDS = 10


def validate_push_endpoint(endpoint: Any) -> str:
    """Only browser push providers may receive server-side HTTP requests.

    An arbitrary HTTPS URL is still an SSRF target (Cloud metadata, private
    services, or a DNS name that resolves to loopback). Restricting the host to
    provider-owned domains also avoids a DNS validation/connect race.
    """
    if not isinstance(endpoint, str) or len(endpoint) > 4096:
        raise ValueError("Invalid push endpoint")
    try:
        parsed = urlsplit(endpoint)
        host = (parsed.hostname or "").lower()
        allowed = host in {
            "fcm.googleapis.com", "android.googleapis.com", "web.push.apple.com",
            "updates.push.services.mozilla.com",
        } or host.endswith(".push.services.mozilla.com") or host.endswith(".notify.windows.com")
        if (parsed.scheme != "https" or not allowed or parsed.port not in {None, 443}
                or parsed.username is not None or parsed.password is not None
                or parsed.fragment or not parsed.path or any(ord(c) < 32 for c in endpoint)):
            raise ValueError("Invalid push endpoint")
    except (TypeError, ValueError) as error:
        raise ValueError("Push endpoint must use a supported HTTPS push provider") from error
    return endpoint


def validate_push_subscription(body: dict[str, Any]) -> tuple[str, str, str]:
    endpoint = validate_push_endpoint(body.get("endpoint"))
    keys = body.get("keys")
    if not isinstance(keys, dict):
        raise ValueError("Missing push keys")
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    if not all(isinstance(value, str) and 0 < len(value) <= 256 for value in (p256dh, auth)):
        raise ValueError("Invalid push keys")
    return endpoint, p256dh, auth


def generate_vapid_keys() -> dict[str, str]:
    """Generate a new VAPID key pair. Run once, store in env vars."""
    from py_vapid import Vapid

    vapid = Vapid()
    vapid.generate_keys()
    return {
        "private_key": vapid.private_pem().decode(),
        "public_key": vapid.public_key_urlsafe_base64(),
    }


def _vapid_claims() -> dict[str, str]:
    return {"sub": os.environ.get("VAPID_MAILTO", "mailto:planner@example.com")}


def _notification_text(title: str, body: str, tag: str | None) -> tuple[str, str]:
    """Keep the task in the prominent system title; timing belongs beneath it.

    Native Android and Telegram retain their own reminder presentation. Only
    known web event reminders use this compact layout, with no HTML or fake
    Unicode fonts that would harm accessibility or task-name readability.
    """
    if not tag or not tag.startswith("event-"):
        return title, body
    match = re.fullmatch(r"[🟡🟢] (?:IN (\d+) MINUTES|STARTING NOW) : (.+)", title, re.DOTALL)
    if not match:
        return title, body
    lead, task = match.groups()
    timing = f"Starts in {lead} min" if lead else "Starting now"
    details = body.removeprefix("Starts at ")
    return task, f"{timing} · {details}" if details else timing


def send_push(
    subscription_info: dict[str, Any],
    title: str,
    body: str,
    url: str = "/",
    tag: str | None = None,
) -> bool:
    """Send a single push notification. Returns True on success.

    tag groups notifications that are about the same thing: sending a second
    one with the same tag replaces the first rather than adding to the pile. A
    task's five-minute warning is an update of its thirty-minute one, so it
    takes the same tag and the phone shows one notification, not two.
    """
    from pywebpush import webpush, WebPushException

    try:
        validate_push_endpoint(subscription_info.get("endpoint"))
    except ValueError:
        logger.warning("Blocked unsupported push endpoint")
        return False

    private_key = os.environ.get("VAPID_PRIVATE_KEY", "")
    if not private_key:
        logger.warning("VAPID_PRIVATE_KEY not set — cannot send push notification")
        return False

    title, body = _notification_text(title, body, tag)
    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url,
        "icon": "/icon-192.png",
        "badge": "/icon-192.png",
        **({"tag": tag} if tag else {}),
    })

    try:
        # Push providers do not redirect sends. Never follow a provider
        # response to an arbitrary URL with our encrypted user payload.
        import requests
        with requests.Session() as push_session:
            push_session.max_redirects = 0
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=private_key,
                vapid_claims=_vapid_claims(),
                ttl=86400,
                timeout=PUSH_TIMEOUT_SECONDS,
                requests_session=push_session,
            )
        return True
    except WebPushException as e:
        status = getattr(e, "response", None)
        if status is not None and hasattr(status, "status_code") and status.status_code in (404, 410):
            # Subscription expired or unsubscribed — caller should delete it
            logger.info("Push subscription gone (HTTP %s), should be removed", status.status_code)
            raise
        logger.error("Push notification failed: %s", e)
        return False
    except Exception as e:
        logger.error("Unexpected push error: %s", e)
        return False


def send_push_to_all(
    gateway: Any,
    user_id: str,
    workspace_id: str,
    title: str,
    body: str,
    url: str = "/",
    tag: str | None = None,
) -> dict[str, int]:
    """Send a push notification to all subscriptions for a user. Returns counts."""
    from pywebpush import WebPushException

    rows = gateway.select(
        "push_subscriptions",
        filters={"user_id": user_id, "workspace_id": workspace_id},
    )

    sent, failed, expired = 0, 0, 0
    for row in rows:
        sub_info = {
            "endpoint": row["endpoint"],
            "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
        }
        try:
            if send_push(sub_info, title, body, url, tag=tag):
                sent += 1
            else:
                failed += 1
        except WebPushException:
            # Gone — remove stale subscription
            try:
                gateway.delete("push_subscriptions", filters={"id": row["id"], "user_id": user_id, "workspace_id": workspace_id})
            except Exception:
                pass
            expired += 1

    return {"sent": sent, "failed": failed, "expired": expired}
