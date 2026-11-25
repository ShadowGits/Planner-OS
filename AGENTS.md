# Repository instructions

Read and follow [.agents/AGENTS.md](.agents/AGENTS.md) before making changes.

Before replacing an installed app or merging a feature branch, inspect all local
worktrees for newer app changes. Committed main is not proof of feature parity
with the installed app. Preserve existing local features and preferences unless
the user explicitly requests removal. Include the kept-feature and floating-clock
UI suites alongside pending-gap and cost tests when integrating Apple changes.

The user explicitly requires future updates to preserve the cost/query budget
unless they specifically request an increase. See [docs/query_budget.md](docs/query_budget.md).
Keep automatic refresh at least 120 seconds apart, share one network loop with
the floating clock, reuse fresh/coalesced date reads, fetch projected data only,
and retain the three-day obsolete-image/build-archive cleanup.

Aim for 60% and stay within the 70% monthly target for Cloud Run free CPU/request
allowances: maximum target 126,000 allocated CPU seconds and 1.4 million requests.
Do not claim this measured in production from local tests, or drop functionality
to enforce it. Require explicit user authorization for increases. Run the query
and image-retention regression tests for changes to these paths.

Record investigations, changes and validation in `docs/debugging/`; never include
credentials or private task content. Never commit local Xcode signing settings
or unrelated unfinished work. Git pushes and deployments require explicit live
chat approval, as specified in `.agents/AGENTS.md`.
