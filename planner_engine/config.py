"""Default configuration for the Google Calendar integration."""

from __future__ import annotations

from pathlib import Path


DEFAULT_PROJECT_ROOT = Path(__file__).parents[1]
DEFAULT_GOOGLE_CONFIG_DIR = DEFAULT_PROJECT_ROOT / ".planner-os"
DEFAULT_GOOGLE_CREDENTIALS_PATH = DEFAULT_GOOGLE_CONFIG_DIR / "credentials.json"
DEFAULT_GOOGLE_TOKEN_PATH = DEFAULT_GOOGLE_CONFIG_DIR / "token.json"
DEFAULT_GOOGLE_CALENDAR_ID = "primary"
DEFAULT_GOOGLE_TIMEZONE = "Asia/Kolkata"
DEFAULT_EXTERNAL_LINKS_PATH = DEFAULT_GOOGLE_CONFIG_DIR / "external-links.json"
