"""Centralized default configuration for Planner OS entry points."""

from __future__ import annotations

from pathlib import Path


DEFAULT_PROJECT_ROOT = Path(__file__).parents[1]
DEFAULT_PLANNER_PATH = Path(
    "/Users/sparry00/Library/CloudStorage/"
    "GoogleDrive-sparsh0304@gmail.com/My Drive/"
    "Life tracking/Master_Planner_Jul26_Jun27.xlsx"
)
DEFAULT_BACKUP_DIR = Path("backups")
DEFAULT_RULES_PATH = Path("config/rules.yaml")
DEFAULT_GOOGLE_CONFIG_DIR = DEFAULT_PROJECT_ROOT / ".planner-os"
DEFAULT_GOOGLE_CREDENTIALS_PATH = DEFAULT_GOOGLE_CONFIG_DIR / "credentials.json"
DEFAULT_GOOGLE_TOKEN_PATH = DEFAULT_GOOGLE_CONFIG_DIR / "token.json"
DEFAULT_GOOGLE_CALENDAR_ID = "primary"
DEFAULT_GOOGLE_TIMEZONE = "Asia/Kolkata"
