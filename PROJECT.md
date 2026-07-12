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
- Be modular so local calendar integrations plug into the same Planner Engine.

## Local MVP2 Architecture

The workbook remains the planning source of truth. Downstream execution is
handled by exactly one persistent active target: `google_calendar`,
`apple_calendar`, or `none`. Changing the target affects future publishing only;
moving existing external items requires an explicit preview and apply.

Apple Calendar uses a small native Swift/EventKit helper with JSON over
stdin/stdout. It does not automate the Calendar UI.

## Principles

1. Architecture over hacks.
2. Never break existing planner behavior.
3. Preserve workbook formatting.
4. Every change should be reversible.
5. Prefer clean, typed, production-quality Python.
