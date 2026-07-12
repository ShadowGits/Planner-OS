# MVP3 Stages 4-6: Authenticated Cloud API Boundary

## Authentication

The API accepts a Supabase access token through `Authorization: Bearer ...`.
The server verifies the JWT signature against the project's JWKS endpoint and
checks issuer, audience, expiry, and subject. The verified `sub` UUID is the
only source of `user_id`; tool payloads cannot provide identity, operation IDs,
workbook paths, or access tokens.

## WorkbookSession

Each tool request resolves an owned workspace through Supabase RLS, downloads
`{user_id}/{workspace_id}/current.xlsx` into a new temporary directory, and
creates an immutable `PlannerContext`. Workbook mutations acquire the workspace
lock, run through the canonical guarded tool registry, create an object-storage
backup, upload the new workbook, and advance the revision. Reads never upload.
Temporary workbooks and request state are deleted at request completion.

## Google Calendar OAuth

Cloud Google Calendar access uses the web-server OAuth flow. The connect route
stores only a SHA-256 hash of a random, ten-minute OAuth state. The callback
atomically consumes that state through the service-role-only migration RPC.
Tokens are encrypted with AES-256-GCM and tenant-bound authenticated data before
they enter `calendar_connections`. Calendar clients and event mappings are
resolved per user and workspace; desktop `credentials.json` and `token.json`
are never read by the cloud path.

## HTTP Surface

- `GET /api/health`
- `GET /api/tools`
- `GET /api/workspaces`
- `POST /api/workspaces`
- `POST /api/workspaces/{workspace_id}/activate`
- `POST /api/workspaces/{workspace_id}/tools/{tool_name}`
- `POST /api/workspaces/{workspace_id}/google-calendar/connect`
- `GET /auth/google/callback`
- `GET /api/workspaces/{workspace_id}/google-calendar/status`
- `DELETE /api/workspaces/{workspace_id}/google-calendar`
- `GET /openapi.json`
- `GET /api/docs`

All failures use a stable Planner OS response envelope and error code. Apple
Calendar tools remain visible in discovery but are explicitly unavailable in
cloud mode.

## Local Development

Apply `0001_mvp3_foundation.sql` and `0002_google_oauth.sql` through Supabase
migrations, then run:

```bash
.venv/bin/uvicorn planner_api.app:app --reload --port 8000
```

No secrets belong in the workbook, migration files, source tree, or logs.
