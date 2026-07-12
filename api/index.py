"""Vercel ASGI entrypoint for the authenticated Planner OS API."""

from planner_api.app import app

__all__ = ["app"]
