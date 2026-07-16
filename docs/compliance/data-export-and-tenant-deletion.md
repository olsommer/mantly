# Data export and tenant deletion procedure

Status: **Production procedure; customer-specific legal review required**

Owner: Authorized tenant-data operator with an independent verifier

This procedure covers customer export, data-subject assistance, and complete
tenant termination across the current PocketBase/application architecture and
configured providers. It must be exercised with synthetic data before a real
customer pilot.

## 1. Safety rules

- Never run a tenant-wide export or deletion from an unverified email request.
- Use an authorized request ID, tenant ID, requester, approval, purpose, and due date.
- Export only the approved tenant and requested scope.
- Do not place exports in public issue attachments, normal support tickets, or
  unencrypted shared storage.
- Pause or disable inbound sync, automation, outbound delivery, and scheduled
  work before a tenant-wide destructive operation.
- Preserve required incident/legal evidence separately and document the reason.
- Treat deletion as complete only after primary, derived, provider, and restore
  paths have been addressed and independently verified.
- A customer or legal request can require a narrower process than complete tenant
  deletion; do not delete unrelated data.

## 2. Required request record

| Field | Required value |
| --- | --- |
| Request ID | Stable internal/customer reference |
| Request type | access/export / correction / restricted deletion / full tenant termination |
| Tenant and projects | IDs and approved customer name |
| Requester and authority | Verified person/role and verification method |
| Customer approval | Authorized customer owner |
| Mantly approval | Data operator plus privacy/security owner for high-risk deletion |
| Scope/data subjects | Identifiers and date/category limits |
| Legal hold/retention exceptions | Scope, reason, approver, expiry |
| Export format/destination | Encrypted destination and recipient |
| Planned disable/deletion time | UTC timestamp |
| Backup snapshot boundary | Last backup before action and expiry/replay treatment |
| Configured providers | Inventory and provider-specific action owner |
| Independent verifier | Person who did not perform the destructive step |
| Completion deadline | Contract/legal operating target |

## 3. System inventory

Before acting, identify every location used by the deployed release:

- PocketBase collections and relation fields;
- PocketBase-managed file/attachment paths;
- `/app/data` application files, exports, caches, local indexes, license cache,
  launch-proof and operational artifacts;
- search/retrieval indexes and extracted text/OCR;
- model/provider prompt or trace storage when enabled;
- email/channel provider mailbox/message copies;
- external CRM/order/support systems changed or synchronized by Mantly;
- observability/log/archive providers;
- payment/billing records;
- encrypted backups and restore tombstone/deletion replay record;
- incident evidence or legal hold;
- temporary operator work directories and locally downloaded exports.

Use the deployed commit and collection/schema inventory. Do not assume this list
is complete for a future connector or customer customization.

## 4. Export procedure

### 4.1 Prepare

1. Verify request and approvals.
2. Select the export cutoff timestamp.
3. Record the deployed commit, schema version, tenant/project IDs, and provider inventory.
4. Decide whether the export is a live consistent export or requires a short
   write pause. For a complete tenant handoff, pause mutations to avoid an
   internally inconsistent snapshot.
5. Create a restricted staging directory with sufficient space.
6. Generate a unique export encryption recipient; do not reuse a public/shared key.

### 4.2 Export content

Export in a documented, portable structure:

```text
manifest.json
tenant.json
users.jsonl
projects.jsonl
runbooks.jsonl
knowledge-sources.jsonl
knowledge-files/
tickets.jsonl
messages.jsonl
attachments/
notes-and-events.jsonl
actions-and-approvals.jsonl
outbound-and-delivery.jsonl
evaluations-and-pilot-metrics.jsonl
settings-and-provider-references.json
checksums.sha256
```

Requirements:

- stable object IDs and relation IDs;
- ISO-8601 UTC timestamps;
- explicit schema/export format version;
- published runbook version and decision/action history;
- attachment original filename, media type, size, hash, parent object, and safe
  relative path;
- provider/credential references without secret values;
- redaction or omission reason when a field cannot be disclosed;
- no password hashes, session tokens, API keys, JWTs, webhook secrets, SMTP
  credentials, backup identities, payment credentials, or hidden system prompts;
- a manifest containing object/file counts, checksums, cutoff time, exclusions,
  generator commit, and operator/verifier.

### 4.3 Verify and deliver

1. Validate every JSON/JSONL file and relative attachment path.
2. Recalculate object counts independently from source and export.
3. Verify every file hash and the manifest/checksum list.
4. Sample relations across users/projects/tickets/messages/attachments/actions.
5. Confirm another tenant's synthetic sentinel data is absent.
6. Scan the export for secret patterns and prohibited infrastructure fields.
7. Encrypt the complete export with the approved recipient.
8. Transfer through the approved channel and provide the checksum separately.
9. Record recipient acknowledgment without storing the decryption identity.
10. Securely remove staging and temporary copies after the agreed window.

## 5. Restricted/data-subject deletion

For one person or limited scope:

1. Resolve the person through customer-approved identifiers.
2. Search messages, contacts/accounts, attachments, notes, customer-portal/CSAT,
   external sync records, knowledge, audit references, logs/traces, exports, and
   providers.
3. Separate customer records that must remain for another valid purpose from
   content that can be deleted or anonymized.
4. Delete or irreversibly anonymize direct content and derived indexes/caches.
5. Preserve only the minimum pseudonymous audit receipt where justified.
6. Send provider deletion requests and record completion/exception.
7. Create a deletion tombstone/replay record for backups without retaining the
   deleted content.
8. Verify search/retrieval and API results no longer return the data.
9. Have an independent verifier review the evidence.

Do not break shared ticket/account records silently. Where one record relates to
several people, redact or detach only the approved subject's content while
preserving required business/audit integrity.

## 6. Full tenant termination

### Phase A — Freeze and return

- [ ] Confirm contract termination, export request, and recovery/deletion window.
- [ ] Disable login or mark tenant suspended at the agreed time.
- [ ] Pause channel ingestion, schedulers, automations, tools, and outbound delivery.
- [ ] Reconcile all claimed, queued, sent, failed, and unknown delivery/action states.
- [ ] Revoke channel, model, CRM/tool, SMTP, webhook, payment, and BYOK credentials.
- [ ] Complete and deliver the approved export.
- [ ] Confirm customer receipt or documented waiver.

### Phase B — Delete active data

Delete or anonymize, in dependency-safe order:

1. temporary exports, import/extraction caches, and local work files;
2. outbound queues, delivery runs/claims, provider message caches;
3. action executions, AI runs, agent messages, approvals, and automation runs;
4. ticket messages, attachments, notes, watchers, CSAT, events, portal/chat sessions;
5. tickets/issues, inbox views, queues, macros, SLA and notification records;
6. knowledge files, chunks/indexes, gaps, sources, articles, and derived summaries;
7. accounts, contacts, external objects, CRM/channel sync/webhook/cursor records;
8. runbook drafts/versions, project settings, tools/configuration references;
9. project memberships, projects, tenant users, and user sessions;
10. tenant billing/license operational state that is not legally required;
11. the tenant record itself;
12. application data paths under `/app/data` scoped to the tenant;
13. configured provider copies under Mantly/customer control.

The exact order depends on schema relation constraints. Use a tested release-
specific deletion plan; do not disable referential protections globally to force
delete completion.

### Phase C — Residual and backup treatment

- remove tenant dashboards, alerts, contacts, and support access;
- remove tenant identifiers/content from normal logs/traces according to their
  bounded retention and redaction capability;
- retain only legally required financial/security evidence in minimized form;
- record which encrypted backups still contain the tenant and their expiry dates;
- maintain a deletion replay/tombstone record until every relevant backup expires;
- when a backup is restored, apply the deletion before user/provider access or
  outbound processing resumes;
- close provider deletion and credential revocation tasks.

## 7. Verification contract

Independent verification must prove:

- tenant users cannot authenticate;
- tenant/project IDs return no accessible records through tenant/admin APIs except
  the authorized minimized deletion receipt;
- PocketBase records and files are absent/anonymized as planned;
- `/app/data` tenant paths, exports, caches, and indexes are absent;
- retrieval cannot return deleted knowledge/message content;
- outbound/action schedulers cannot process deleted tenant work;
- channel/model/tool credentials are revoked;
- providers confirm deletion or an exception/retention basis is documented;
- another tenant's data remains intact;
- active backups are listed with expiry and replay control;
- restore-after-deletion exercise does not reintroduce accessible tenant data.

Verification evidence should contain counts, object IDs/hashes, queries, and
pass/fail results rather than deleted content.

## 8. Deletion receipt

A receipt may retain:

- request ID and type;
- pseudonymous tenant/requester reference;
- scope and cutoff;
- start/completion timestamps;
- operator and verifier;
- deleted/anonymized class counts;
- provider completion/exception status;
- legal hold/retention exceptions and expiry;
- backup objects/expiry covered by replay;
- result and open corrective actions.

It must not contain message/attachment bodies, secrets, or a data copy sufficient
to reconstruct the deleted customer record.

## 9. Failure and incident handling

Stop and escalate when:

- tenant scope cannot be proved;
- source/export counts cannot be reconciled;
- another tenant's sentinel appears in the export;
- deletion affects another tenant;
- required data reappears through retrieval/cache;
- a provider result is unknown;
- a queued/claimed side effect remains unreconciled;
- a backup restore reintroduces accessible deleted data;
- required evidence is missing.

A cross-tenant export or deletion is a security incident. Follow
`docs/security/incident-response.md` and preserve evidence before further
changes.

## 10. Synthetic exercise before pilot

Create two synthetic tenants, each with:

- users/roles/projects;
- three runbook versions;
- knowledge source and file;
- ticket, messages, attachment, note, audit event;
- action execution/approval;
- outbound queue/delivery attempt;
- metric/evaluation record;
- unique sentinel values in PocketBase, files, and retrieval index.

Exercise:

1. export tenant A and prove tenant B sentinel absence;
2. restricted deletion for one tenant A contact;
3. full tenant A termination;
4. verify tenant B remains complete;
5. restore a backup created before tenant A deletion into isolation;
6. replay the deletion record;
7. prove tenant A remains inaccessible/deleted and tenant B remains complete.

Attach redacted results to the pilot readiness evidence. Real customer processing
is blocked until this exercise passes or a time-bounded risk acceptance is
approved.
