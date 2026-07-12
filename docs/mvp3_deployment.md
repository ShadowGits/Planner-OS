# Planner OS MVP3 Deployment

Planner OS MVP3 uses a Next.js interface, a FastAPI function, and the linked Supabase project. The workbook remains the planning source of truth in the private `planner-workbooks` bucket.

## 1. Apply migrations

Link the repository to the intended Supabase project, review the target project reference, then apply only checked-in migrations:

```bash
supabase migration list --linked
supabase db push --linked
```

The expected migrations are:

- `0001_mvp3_foundation.sql`
- `0002_google_oauth.sql`

Do not create or modify production tables manually. Confirm `workspaces`, `planner_operations`, `planner_previews`, `calendar_connections`, and `calendar_event_mappings` before deployment.

## 2. Configure Vercel

Create one Vercel project from this repository. Add these encrypted environment variables for Preview and Production:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `GOOGLE_WEB_CLIENT_ID`
- `GOOGLE_WEB_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI`
- `PLANNER_WEB_APP_URL`
- `PLANNER_WEB_ORIGINS`
- `PLANNER_CREDENTIAL_ENCRYPTION_KEY` (recommended for production)

Use the same Supabase URL and anonymous key for their `NEXT_PUBLIC_` counterparts. Never expose the service-role key, Google client secret, or credential-encryption key as public variables.

Run `npm run check:env` in the configured deployment environment before release.

## 3. Configure Google OAuth

Add the production callback to the Google web OAuth client:

```text
https://YOUR_DOMAIN/auth/google/callback
```

Set `GOOGLE_OAUTH_REDIRECT_URI` to that exact value. Set `PLANNER_WEB_APP_URL` to `https://YOUR_DOMAIN` and `PLANNER_WEB_ORIGINS` to the same origin. Keep the localhost callback for local development only.

## 4. Verify two users

1. Create User A and User B with separate browser profiles.
2. Upload a different workbook for each user.
3. Confirm each account lists only its own workspace.
4. Attempt User A access to User B's workspace UUID and confirm a not-found response.
5. Create and apply a preview as User A; confirm User B cannot read or apply its ID.
6. Connect separate Google accounts and publish one dated task from each workspace.
7. Confirm each event mapping belongs to the correct user and workspace.
8. Run two writes against one workspace and confirm the second waits or receives a conflict without overwriting the first.
9. Download both workbooks and confirm each contains only that user's changes.

## 5. Release gate

Run:

```bash
npm run lint
npm run build
python -m pytest
git diff --check
```

Deploy a Vercel preview first. Complete the two-user verification against the preview before promoting it to production.
