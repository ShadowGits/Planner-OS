# Planner OS

## Mission

Build an autonomous personal productivity assistant for Shadow.

The assistant should:

- Use Excel as the single source of truth.
- Follow predefined planning rules and guardrails.
- Edit the planner immediately after decisions.
- Create automatic backups before every modification.
- Optimize plans rather than simply executing commands.
- Track daily, weekly, and monthly progress.
- Learn user behavior over time without treating learned patterns as permanent facts.
- Be modular so future integrations (Google Calendar, Structured, Gmail, WhatsApp, Slack, etc.) plug into the same Planner Engine.

## Principles

1. Architecture over hacks.
2. Never break existing planner behavior.
3. Preserve workbook formatting.
4. Every change should be reversible.
5. Prefer clean, typed, production-quality Python.
