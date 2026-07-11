# Planner OS Roadmap

> Last updated: 11 Jul 2026

---

# Vision

Build an autonomous personal operating system that understands my life, maintains my planner, adapts to change, and executes through natural conversation.

Excel remains the source of truth until a future storage migration is justified.

---

# Design Principles

- Conversation is the primary interface.
- Planner Engine is the single source of planning logic.
- Excel is the source of truth.
- Every modification is semantic, never cell-based.
- Every write is reversible.
- Architecture over shortcuts.
- Ship small, stable iterations.

---

# Version History

## ✅ v1.0 — Core Planner Engine

### Planner Core

- [x] Excel Store
- [x] Planner Engine
- [x] Rules Engine
- [x] Reader
- [x] Scheduler
- [x] Progress Engine
- [x] Semantic Writer
- [x] Planner Importer

### Interfaces

- [x] Shadow CLI
- [x] Planner MCP Server

### Quality

- [x] Automated tests
- [x] Backup & rollback
- [x] Typed models
- [x] Configuration layer

Status:
**COMPLETE**

---

# v1.1 — Personal Assistant

## Decision Log

- [ ] Record every planner-changing action
- [ ] Store timestamp, action, reason, affected tasks, and outcome
- [ ] Make decisions auditable and reversible
- [ ] Expose recent decisions through ChatGPT

## Calendar

- [ ] Google Calendar integration
- [ ] Apple Calendar integration (optional)

> At least one direct calendar integration is required before closing v1.1.

## Cloud Execution

- [ ] GitHub Actions backend
- [ ] Cloud Run backend (optional replacement)

## Conversation

- [ ] One-thread planner management
- [ ] Add custom items
- [ ] Daily completion updates
- [ ] Planner edits through ChatGPT

Status:
Planned

---

# v1.2 — Intelligence

- [ ] Automatic replanning
- [ ] Constraint optimization
- [ ] Better duration estimation
- [ ] Smarter prioritization
- [ ] Habit prediction
- [ ] Adaptive scheduling

Status:
Future

---

# v2.0 — Planner OS Platform

- [ ] Replace Excel if justified
- [ ] Mobile companion
- [ ] Multi-device sync
- [ ] User accounts
- [ ] Public API
- [ ] Multi-user support

Status:
Long-term

---

# Out of Scope

These will not be added unless explicitly reprioritized.

- Web frontend
- Desktop GUI
- Database migration
- AI-generated scheduling heuristics beyond Planner Engine
- Multiple planner formats
- Plugin ecosystem

---

# Current Focus

Current version:
**v1.1**

Milestones:
1. Decision Log
2. Direct Google Calendar integration
3. Cloud execution route
4. One-thread planner management

No additional features should be added until these milestones are complete.
