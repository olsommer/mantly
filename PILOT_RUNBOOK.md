# Pilot Runbook

This runbook is for a founder-led pilot, not public self-serve onboarding.

The pilot must follow the [active email-first V1 scope](docs/v1-scope.md) and the
[precommitted success criteria](docs/pilot-success-criteria.md). A broader
capability already present in the repository is not automatically part of the
pilot contract.

## Goal

Onboard one design-partner firm from a clean auth-enabled deployment to:

1. bootstrap the first admin;
2. configure the tenant;
3. provision a user;
4. force the first password change;
5. install the Outlook add-in;
6. configure the selected email workflow and three V1 runbooks;
7. validate metric capture with synthetic tickets;
8. process the first real customer email;
9. complete the agreed real-ticket sample and make an evidence-based commercial decision.

## Scope and measurement lock

Before configuring the environment:

1. copy `docs/pilot-targets.example.yml` into the customer-specific pilot folder;
2. complete every required target, owner, date, runbook version, and exclusion rule;
3. record the selected:
   - design-partner segment;
   - email queue or mailbox;
   - operational owner and economic buyer;
   - three runbooks;
   - approved knowledge sources;
   - approved tools and action permissions;
   - autonomy and review boundary for each runbook;
   - baseline period, ticket sample, observation window, and pilot dates;
4. approve the target file before any real ticket is counted;
5. retain the original approved targets if they are later changed, including the reason and approver.

Do not add a channel or unrelated workflow during the pilot without updating
`docs/v1-scope.md` and documenting the reason in roadmap epic #12.

## Preconditions

- Production-like deployment uses the same compose and Dockerfiles as production.
- `REQUIRE_AUTH=true`.
- PocketBase admin credentials are set via env:
  - `PB_ADMIN_EMAIL`;
  - `PB_ADMIN_PASSWORD`.
- FastAPI JWT secret is set:
  - `JWT_SECRET`.
- Public app URL is set:
  - `PUBLIC_URL`.
- PocketBase public URL is set at build time:
  - `VITE_PB_URL`.
- The selected model/provider credentials are configured.
- The operational owner has approved the runbooks, knowledge sources, tool permissions, and review boundaries.
- `docs/pilot-targets.example.yml` has been copied, completed, and approved for this pilot.
- Baseline data has been collected using the same inclusion and exclusion rules as the pilot.
- Metric records validate against `docs/pilot-metrics-schema.json`.
- Security, privacy, recovery, and CI blockers are closed or have a documented owner, mitigation, and expiry date.

## Important production defaults

- Do not enable `ENABLE_DEMO_MODE`.
- Do not enable `VITE_ENABLE_DEMO_MODE`.
- Mock mode is for local browser testing only.
- Preview/embed is an authenticated admin workflow. Enable it only when the pilot
  needs admin-side draft preview.
- Automatic financial or irreversible actions remain disabled unless explicitly
  approved in the pilot risk register.
- A runbook is paused immediately after a critical unsafe/materially incorrect
  outcome, suspected tenant-isolation incident, duplicate irreversible side
  effect, or missing required execution trace.

## Bootstrap first admin

The first tenant admin still needs to be created manually once.

Option A: PocketBase UI

- Open `https://<your-pocketbase-host>/_/`.
- Create a tenant record in `tenants`.
- Create a `users` record with:
  - `email`;
  - `password`;
  - `tenant`;
  - `is_admin=true`;
  - `verified=true`;
  - `must_change_password=false`.

Option B: PocketBase CLI / API

- Use the PocketBase superuser account and create the tenant and initial admin record directly.

## Founder-led onboarding flow

1. Open the admin app and sign in as the bootstrap admin.
2. Confirm the `Users` page loads.
3. Open `Settings` and enter the tenant-specific organisation details.
4. Configure only the knowledge, channel, and tool paths required by the selected V1 workflow.
5. Create or import the three approved runbooks.
6. Run their simulation/evaluation and publish only the reviewed versions recorded in the target file.
7. Use `Users` to create the pilot user with a temporary password.
8. Share the temporary password with the user through a secure channel.
9. Ask the user to sign in to the add-in with the temporary password.
10. Confirm the forced password-change screen appears immediately.
11. Confirm the user can access the normal add-in after changing the password.
12. Install the Outlook manifest from the admin app or side-load `addin/manifest.xml` through the Microsoft 365 admin path.
13. Replay one synthetic example for each runbook and one explicit no-match case.
14. Export or inspect the synthetic metric records and validate:
    - eligibility and handling classification;
    - runbook ID and published version;
    - action and delivery attempts;
    - human touches and approval status;
    - quality-review fields;
    - token/cost fields where a model was used;
    - observation-window state.
15. Open a real pilot email in Outlook and run the first analysis.
16. Confirm one of these outcomes:
    - the configured automatic path completes;
    - a draft response is generated;
    - the email is routed into manual review.
17. Confirm the ticket, selected runbook, actions, approvals, response, delivery state, and failures appear in history/audit data.
18. Confirm the ticket contributes to the pilot metric dataset with the correct handling classification.
19. Start the configured observation window before promoting an autonomous candidate to verified autonomous.

## Smoke checklist

- Admin login works.
- Forgot-password request returns success.
- Admin can create a user.
- New user is marked `Password change required`.
- First login forces password change.
- Second login works normally.
- Non-admin user cannot access admin endpoints.
- Cross-tenant user deletion is blocked.
- Demo scenario picker is not visible.
- Admin preview is visible only when explicitly enabled for the pilot.
- The three published runbooks match the versions in the approved target file.
- A no-match ticket routes to manual handling.
- Tool/action permissions match the approved runbook definitions.
- Duplicate email delivery does not create duplicate side effects.
- First real email can be analyzed from Outlook.
- Outbound failure remains visible and recoverable.
- The complete execution trace is available.
- A synthetic metric record validates against `docs/pilot-metrics-schema.json`.
- Excluded tickets require an approved machine-readable exclusion reason.
- An autonomous candidate cannot become verified autonomous before review and the observation window close.

## Local dry-run commands

Backend:

```bash
cd backend && uv run ruff check automail/ tests/
cd backend && uv run pyright
cd backend && uv run pytest -v
```

Frontend:

```bash
cd addin && npm run lint
cd addin && npm run build
cd admin && npm run lint
cd admin && npm run build
cd addin && npm run test:e2e:auth
```

Packaging:

```bash
./build.sh
```

## Local demo-only flags

Use these only for local demos or internal debugging:

- `VITE_ENABLE_MOCK_MODE=true`;
- `VITE_ENABLE_DEMO_MODE=true`;
- `ENABLE_DEMO_MODE=true`.

These should remain unset for pilot/prod builds.

## Support notes during pilot

- If login fails, first verify PocketBase health and the `users` collection schema.
- If password reset appears broken in the browser, confirm PocketBase mail delivery is configured in the target environment.
- If the add-in opens outside Outlook, that is expected only in local mock mode.
- If a user cannot see emails/chats they expect, check tenant assignment on the user record first.
- If a runbook match is uncertain, stop automation and classify the ticket for manual handling; do not tune the production threshold ad hoc without recording the change.
- If an external action partially fails, preserve the execution state and follow the incident or recovery procedure rather than replaying the entire ticket blindly.
- If metric capture is incomplete, preserve the ticket for customer handling but exclude the incomplete record from success claims until the evidence is repaired and reviewed.

## Environment-ready exit criteria

The pilot environment is ready for controlled real-ticket processing when:

- the first admin can sign in without manual schema fixes;
- an admin can provision users from the admin SPA;
- the forced password-change flow works;
- the add-in no longer exposes stale demo/preview entry points by default;
- the selected email workflow and three runbooks are configured and reviewed;
- synthetic happy-path, no-match, failure-path, and duplicate-delivery checks pass;
- the approved target file and baseline exist;
- synthetic metric records validate against the schema;
- the first pilot email can be processed end to end in Outlook;
- the result is visible in audit history and the pilot metric dataset.

Environment readiness is not pilot success. The pilot is successful only when the
real-ticket sample is completed and assessed against the precommitted success
criteria, including an explicit customer continuation decision.
