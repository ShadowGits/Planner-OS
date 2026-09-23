"""Web Push sending.

These cover the one property that took the service down: every call out to a
push service has to be bounded. A push endpoint that accepts the connection
and never answers is not a slow notification, it is a thread held for ever,
and the reminder cron sends to every subscription every five minutes.
"""

from __future__ import annotations

import sys
import types

import pytest

from planner_core.push import PUSH_TIMEOUT_SECONDS, send_push, send_push_to_all


class _WebPushException(Exception):
    def __init__(self, message="gone", response=None):
        super().__init__(message)
        self.response = response


@pytest.fixture()
def fake_pywebpush(monkeypatch):
    """Stand in for pywebpush and record how webpush was called.

    The real package needs http-ece compiled, and the thing worth asserting is
    the arguments we hand it, not its encryption.
    """
    calls: list[dict] = []
    module = types.ModuleType("pywebpush")

    def webpush(**kwargs):
        calls.append(kwargs)
        return True

    module.webpush = webpush
    module.WebPushException = _WebPushException
    monkeypatch.setitem(sys.modules, "pywebpush", module)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "test-key")
    return calls


def _subscription(endpoint="https://web.push.apple.com/abc"):
    return {"endpoint": endpoint, "keys": {"p256dh": "p", "auth": "a"}}


def test_every_push_is_sent_with_a_timeout(fake_pywebpush):
    assert send_push(_subscription(), "Title", "Body") is True

    timeout = fake_pywebpush[0].get("timeout")
    # Not merely present: pywebpush forwards timeout=None whether or not the
    # caller set it, and requests.post(timeout=None) waits for ever.
    assert timeout is not None, "webpush was called without a timeout"
    assert 0 < timeout <= 30, f"timeout must be short and finite, got {timeout!r}"
    assert timeout == PUSH_TIMEOUT_SECONDS


def test_a_subscription_that_times_out_does_not_stop_the_rest(fake_pywebpush, monkeypatch):
    """One dead endpoint must not cost the others their notification."""
    import planner_core.push as push

    def flaky(**kwargs):
        fake_pywebpush.append(kwargs)
        if "dead" in kwargs["subscription_info"]["endpoint"]:
            raise TimeoutError("read timed out")
        return True

    monkeypatch.setattr(sys.modules["pywebpush"], "webpush", flaky)

    class Gateway:
        deleted: list = []

        def select(self, table, *, filters=None, **kwargs):
            assert table == "push_subscriptions"
            return [
                {"id": "1", "endpoint": "https://push/dead", "p256dh": "p", "auth": "a"},
                {"id": "2", "endpoint": "https://push/live", "p256dh": "p", "auth": "a"},
            ]

        def delete(self, table, *, filters):
            self.deleted.append(filters)

    result = push.send_push_to_all(Gateway(), "user", "workspace", "Title", "Body")

    assert result["sent"] == 1
    assert result["failed"] == 1
    assert len(fake_pywebpush) == 2, "the live subscription was still attempted"


def test_an_expired_subscription_is_retired(fake_pywebpush, monkeypatch):
    import planner_core.push as push

    class Response:
        status_code = 410

    def gone(**kwargs):
        raise _WebPushException("gone", response=Response())

    monkeypatch.setattr(sys.modules["pywebpush"], "webpush", gone)

    class Gateway:
        def __init__(self):
            self.deleted: list = []

        def select(self, table, *, filters=None, **kwargs):
            return [{"id": "1", "endpoint": "https://push/x", "p256dh": "p", "auth": "a"}]

        def delete(self, table, *, filters):
            self.deleted.append(filters)

    gateway = Gateway()
    result = push.send_push_to_all(gateway, "user", "workspace", "Title", "Body")

    assert result["expired"] == 1
    assert gateway.deleted == [{"id": "1"}]
