"""Dependency-free Telegram Bot API transport for reminders and tick-back."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TelegramError(RuntimeError):
    """Sanitized Telegram transport error."""


class TelegramClient:
    def __init__(self, bot_token: str, chat_id: str, timeout_seconds: int = 15) -> None:
        if not bot_token or not chat_id:
            raise TelegramError("Telegram bot token and chat id are required")
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> "TelegramClient | None":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return None
        return cls(token, chat_id)

    def send_message(self, text: str) -> None:
        payload = json.dumps({"chat_id": self.chat_id, "text": text}).encode("utf-8")
        request = Request(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds):
                return
        except HTTPError as error:
            raise TelegramError(f"Telegram send failed with HTTP {error.code}") from error
        except URLError as error:
            raise TelegramError("Telegram could not be reached") from error


def parse_command(update: dict[str, Any]) -> tuple[str, str] | None:
    """Extract (command, argument) from a Telegram webhook update.

    Supported: "done <text>", "today", "status". Returns None for anything
    else (other chats, edits, stickers) so the webhook can ignore it.
    """
    message = update.get("message") or {}
    text = str(message.get("text") or "").strip()
    if not text:
        return None
    lowered = text.casefold()
    if lowered.startswith("done ") and len(text) > 5:
        return ("done", text[5:].strip())
    if lowered in {"today", "/today"}:
        return ("today", "")
    if lowered in {"status", "/status"}:
        return ("status", "")
    return None


def sender_chat_id(update: dict[str, Any]) -> str | None:
    chat = (update.get("message") or {}).get("chat") or {}
    identifier = chat.get("id")
    return str(identifier) if identifier is not None else None
