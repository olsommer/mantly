# Credential rotation and break-glass operations

Status: **Required operational procedure. Deployment-specific account IDs,
vault paths, and contacts must be recorded before production-like customer use.**

- Owner: Platform security owner
- Backup owner: Incident commander on call
- Evidence owner: Incident scribe or change operator

This runbook defines how Mantly production credentials are inventoried, rotated,
revoked, and accessed during an emergency. It never records secret values.

## 1. Required credential inventory

The deployment evidence register must contain one row per credential with:

- secret class and environment;
- owning tenant or global scope;
- secret-store reference, never the value;
- provider/account identifier;
- primary and backup owner;
- creation and last-rotation timestamp;
- normal rotation interval;
- revocation method;
- dependent services;
- validation command or synthetic check;
- next rotation due date.

Required classes:

| Class | Mantly configuration | Rotation consequence |
| --- | --- | --- |
| Session signing | `JWT_SECRET` | Invalidates active Mantly sessions; users must sign in again |
| PocketBase superuser | `PB_ADMIN_EMAIL`, `PB_ADMIN_PASSWORD` | Bootstrap, migrations, backup verification, and server-side storage access must use the replacement |
| Initial/operator accounts | `SETUP_ADMIN_*`, named operator credentials | Replace or disable bootstrap credentials after first use; revoke affected sessions |
| Model providers | `MANTLY_MANAGED_LLM_API_KEY`, tenant BYOK references | Replace provider key, update secret store, verify minimal synthetic inference, revoke old key |
| SMTP and channels | SMTP password, OAuth refresh token, webhook signing secret | Pause affected channel, rotate/re-authorize, verify inbound signature and outbound test, revoke old credential |
| Billing and licensing | Stripe keys/webhook secret, license-signing or registry tokens | Disable affected write path until replacement and signature/webhook verification pass |
| Observability | Tracing, metrics, and log-shipping tokens | Disable exporter if safe replacement cannot be confirmed without exposing customer content |
| Backup encryption | `BACKUP_AGE_RECIPIENT`, protected age identity | New backups use new recipient; old identity remains restricted until every backup encrypted to it expires or is re-encrypted and verified |
| Deployment control | Coolify, registry, DNS, and TLS credentials | Rotate at provider, update protected automation, verify read-only status before enabling writes |

## 2. Standard rotation

1. Open a private change record. Record operator, approver, reason, scope,
   affected tenants, start time, and rollback owner.
2. Identify every dependent service from the credential register.
3. Create the replacement in the provider or secret store with equal or narrower
   privilege. Do not revoke the old credential yet unless exposure is suspected.
4. Update the deployment secret reference. Never paste the value into a ticket,
   shell history, log, or pull request.
5. Restart only affected services. Record image digest and configuration version.
6. Run the listed validation:
   - authentication plus cross-tenant denial for session/storage credentials;
   - one synthetic provider request for model, SMTP, or channel credentials;
   - signature/replay rejection for webhook secrets;
   - encrypted backup creation plus manifest verification for backup keys.
7. Revoke the old credential and active sessions/tokens that it could mint.
8. Repeat validation after revocation. Roll back by disabling the affected path,
   not by silently restoring a suspected-compromised secret.
9. Record completion, verification evidence, failures, and next due date.

Rotation is incomplete until the old credential is revoked or a time-bounded,
approved overlap is recorded. Maximum planned overlap: 24 hours.

## 3. Emergency exposure response

For suspected exposure, declare an incident and use this order:

1. Disable the smallest affected ingress, scheduler, tool, exporter, or customer
   action that stops further harm.
2. Preserve provider audit events, redacted application logs, request IDs, and
   configuration metadata.
3. Revoke the exposed credential. When immediate revocation would destroy
   required evidence or cause broader harm, document incident-commander approval
   and a maximum 60-minute containment window.
4. Rotate all credentials the exposed secret could read, derive, or mint.
5. Invalidate sessions and queued work whose authorization depended on it.
6. Verify tenant isolation and check for unauthorized or duplicate side effects.
7. Follow `docs/security/incident-response.md` for notification, recovery, and
   post-incident review.

## 4. Break-glass access

Break-glass access exists only for loss of normal administrative access or an
active incident requiring an otherwise unavailable privileged operation.

- One named primary and one named backup account. No shared daily-use account.
- Credentials stored in a protected offline or independently controlled vault.
- Two-person approval: incident commander plus platform security owner. If one is
  unavailable during SEV-0 containment, one operator may activate access but must
  notify the backup owner immediately and obtain retrospective approval within
  four hours.
- Access lifetime: maximum 60 minutes. Extend only with a new recorded approval.
- Scope: minimum provider, environment, and action needed.
- Audit: record activation, approvers, reason, commands/actions, affected objects,
  provider audit-event IDs, and deactivation time.
- On exit: revoke the session/token, rotate the break-glass credential, verify
  normal access, and attach redacted evidence to the incident or drill record.

Break-glass access must never bypass tenant isolation, action approval, or
evidence preservation merely for convenience.

## 5. Validation cadence

- Review credential inventory monthly.
- Rotate at provider-required intervals and immediately after exposure, owner
  departure, privilege change, or unauthorized vault access.
- Exercise one standard rotation and one break-glass drill before the first real
  pilot and quarterly thereafter.
- Test session-signing, PocketBase, model-provider, channel/webhook, and backup
  key paths at least annually even when their normal rotation interval is longer.

Each drill records date, environment, synthetic scope, operators, approvals,
downtime, failed steps, recovery result, and follow-up owners/dates. A blank
template is not evidence of a completed drill.
