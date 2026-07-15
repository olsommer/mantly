# Pilot Runbook

This runbook is for a founder-led pilot, not public self-serve onboarding.

## Goal

Onboard one firm from a clean auth-enabled deployment to:

1. bootstrap the first admin
2. configure the tenant
3. provision a user
4. force the first password change
5. install the Outlook add-in
6. process the first real customer email

## Preconditions

- Production-like deployment uses the same compose and Dockerfiles as production.
- `REQUIRE_AUTH=true`
- PocketBase admin credentials are set via env:
  - `PB_ADMIN_EMAIL`
  - `PB_ADMIN_PASSWORD`
- FastAPI JWT secret is set:
  - `JWT_SECRET`
- Public app URL is set:
  - `PUBLIC_URL`
- PocketBase public URL is set at build time:
  - `VITE_PB_URL`
- Google model key is set:
  - `GOOGLE_API_KEY`

## Important Production Defaults

- Do not enable `ENABLE_DEMO_MODE`
- Do not enable `VITE_ENABLE_DEMO_MODE`
- Mock mode is for local browser testing only
- Preview/embed is an authenticated admin workflow. Enable it only when the pilot
  needs admin-side draft preview.

## Bootstrap First Admin

The first tenant admin still needs to be created manually once.

Option A: PocketBase UI
- Open `https://<your-pocketbase-host>/_/`
- Create a tenant record in `tenants`
- Create a `users` record with:
  - `email`
  - `password`
  - `tenant`
  - `is_admin=true`
  - `verified=true`
  - `must_change_password=false`

Option B: PocketBase CLI / API
- Use the PocketBase superuser account and create the tenant and initial admin record directly

## Founder-Led Onboarding Flow

1. Open the admin app and sign in as the bootstrap admin.
2. Confirm the `Users` page loads.
3. Open `Settings` and enter the tenant-specific organisation details.
4. Configure at least one live intent/tool path needed for the pilot.
5. Use `Users` to create the pilot user with a temporary password.
6. Share the temporary password with the user through a secure channel.
7. Ask the user to sign in to the add-in with the temporary password.
8. Confirm the forced password-change screen appears immediately.
9. Confirm the user can access the normal add-in after changing the password.
10. Install the Outlook manifest from the admin app or side-load `addin/manifest.xml` through the Microsoft 365 admin path.
11. Open a real pilot email in Outlook and run the first analysis.
12. Confirm one of these outcomes:
    - a draft response is generated
    - the email is routed into manual review
13. Confirm the processed email appears in analytics/history as expected.

## Smoke Checklist

- Admin login works
- Forgot-password request returns success
- Admin can create a user
- New user is marked `Password change required`
- First login forces password change
- Second login works normally
- Non-admin user cannot access admin endpoints
- Cross-tenant user deletion is blocked
- Demo scenario picker is not visible
- Admin preview is visible only when explicitly enabled for the pilot
- First real email can be analyzed from Outlook

## Local Dry-Run Commands

Backend:

```bash
cd backend && uv run ruff check automail/ tests/
cd backend && uv run pytest tests/test_tenant_isolation.py tests/test_prompt_and_tool.py tests/test_preferences.py -v
```

Frontend:

```bash
cd addin && npm run lint
cd admin && npm run lint
cd addin && npm run test:e2e:auth
```

Packaging:

```bash
./build.sh
```

## Local Demo-Only Flags

Use these only for local demos or internal debugging:

- `VITE_ENABLE_MOCK_MODE=true`
- `VITE_ENABLE_DEMO_MODE=true`
- `ENABLE_DEMO_MODE=true`

These should remain unset for pilot/prod builds.

## Support Notes During Pilot

- If login fails, first verify PocketBase health and the `users` collection schema.
- If password reset appears broken in the browser, confirm PocketBase mail delivery is configured in the target environment.
- If the add-in opens outside Outlook, that is expected only in local mock mode.
- If a user cannot see emails/chats they expect, check tenant assignment on the user record first.

## Exit Criteria

The pilot environment is considered ready when:

- the first admin can sign in without manual schema fixes
- an admin can provision users from the admin SPA
- the forced password-change flow works
- the add-in no longer exposes stale demo/preview entry points by default
- the first pilot email can be processed end to end in Outlook
