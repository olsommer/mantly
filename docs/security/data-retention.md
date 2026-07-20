# Data retention and deletion

Status: **Production baseline; customer-specific periods require contractual and legal review**

Owner: Product/privacy owner with engineering implementation owner

This document defines the default retention classes and the controls Mantly must
support. It is not legal advice and does not replace a customer Data Processing
Agreement or jurisdiction-specific retention requirement.

## 1. Principles

- Collect and retain only what is required for the configured support purpose,
  security, billing, and agreed evidence.
- A tenant's configured period may shorten the defaults unless a documented legal
  hold or mandatory requirement applies.
- Deletion covers derived data and search/retrieval indexes, not only the primary
  record.
- Customer content is not copied into metrics or logs when a stable reference or
  classification is sufficient.
- Backups have a bounded retention period and are not restored into normal
  production without replaying valid deletion requests.
- Legal holds are explicit, scoped, access controlled, auditable, and reviewed.
- Deletion is verifiable through counts, identifiers, and integrity checks without
  retaining the deleted content itself.

## 2. Data classes and default periods

These defaults are conservative operational starting points. The production
configuration and customer agreement are authoritative.

| Data class | Examples | Default retention | Deletion behavior |
| --- | --- | ---: | --- |
| Active ticket data | Messages, participants, status, notes, actions, delivery state | Customer-configured; proposed default 365 days after resolution | Delete or irreversibly anonymize content and derived records |
| Attachments | Email files, uploads, extracted text/OCR | Same as parent ticket or knowledge source | Delete binary, derivatives, thumbnails, extraction cache, and index entries |
| Knowledge sources | Uploaded policies, website snapshots, source metadata | Until source removal or tenant termination | Delete source, chunks/index, cached extracts, and derived summaries |
| Runbooks/configuration | Drafts, published versions, policies, permissions | While tenant active plus 90 days after termination unless exported/deleted earlier | Delete tenant-specific content; retain non-content security evidence only when justified |
| Audit events | Authentication, publication, approval, action, delivery, admin changes | Proposed default 400 days | Retain minimized event metadata; remove message/attachment bodies |
| Security logs | Access/error/security events, request IDs | 30–90 days online; up to 400 days restricted archive for agreed environments | Redact content/secrets; delete by rolling policy |
| Application logs | Runtime diagnostics | 30 days | Redact by default and expire automatically |
| Model traces | Prompt/response traces in approved provider | Disabled by default for content; when enabled, 7–30 days | Provider and local deletion must be documented |
| Pilot metrics | Classifications, timing, costs, review outcomes, evidence references | Pilot duration plus 12 months or customer-agreed period | Delete/anonymize tenant identifiers and evidence links at end |
| Billing records | Subscription, invoices, usage totals | According to applicable accounting/tax requirements | Keep legally required minimized financial record; remove support content |
| Backups | Encrypted database and attachment snapshots | 30 days rolling by default | Expire automatically; deletion requests replayed after restore |
| Incident evidence | Scoped logs/exports and timeline | According to severity, legal need, and incident policy | Restricted, reviewed, and deleted when no longer required |
| User account/profile | Email, role, tenant/project memberships | Until account deletion/tenant termination plus short recovery window | Disable immediately; delete/anonymize after recovery window |

## 3. Tenant-configurable retention

A production deployment must support or document:

- ticket retention in days after resolution;
- attachment retention, no longer than the parent ticket unless explicitly
  required;
- knowledge source retention and immediate source removal;
- audit-log retention within the supported minimum/maximum range;
- model-trace enablement and retention;
- inactive user deletion;
- tenant termination date and deletion schedule;
- legal hold override with reason and approver.

Changes to retention configuration are privileged audit events. Reducing a period
must schedule the affected data for deletion; increasing a period does not restore
already deleted data.

## 4. User and data-subject deletion

A deletion request must:

1. authenticate and authorize the requester or follow the customer's documented
   verification process;
2. identify tenant, user/customer identity, and relevant systems;
3. search primary and derived records using controlled identifiers;
4. distinguish data that can be deleted, must be retained, or must be anonymized;
5. remove ticket/customer profile data, attachments, knowledge content,
   retrieval/index entries, exports, caches, and model traces under Mantly control;
6. notify configured subprocessors where their API/contract supports deletion;
7. record a minimized deletion receipt containing request ID, scope, completion
   time, exceptions, and verifier;
8. ensure a later backup restore replays the deletion before returning to service.

Audit events may retain a pseudonymous object reference and action type when
required for security/accountability, but not the deleted message or attachment
content.

## 5. Tenant termination

At contract/pilot termination:

- disable user access and inbound/outbound connectors at the agreed time;
- stop automation and scheduled work;
- provide an agreed export before deletion where requested;
- revoke tenant-specific credentials and provider keys;
- delete active data after the contractual recovery/export window;
- expire backups through the normal bounded cycle;
- provide a deletion confirmation identifying residual legally retained classes;
- remove tenant configuration from monitoring, billing, and incident contacts.

Proposed default recovery/export window: **30 days** after termination. A customer
may require immediate deletion or a different contract period.

## 6. Backup treatment

Backups are immutable snapshots and may contain data deleted from the live system
after the snapshot was taken.

Required controls:

- bounded backup retention;
- encryption and separate access control;
- backup inventory with creation and expiry timestamps;
- no ad-hoc indefinite backup copies;
- restore procedure that applies all valid deletion/tombstone records created
  after the backup timestamp before production access resumes;
- documentation of the maximum period deleted data may remain only in an
  inaccessible backup;
- secure destruction of expired backup objects and keys according to the storage
  provider's capabilities.

## 7. Logs and redaction

Logs, metrics, and traces must not become an uncontrolled secondary data store.

Never log by default:

- complete message or attachment bodies;
- passwords, JWTs, API keys, OAuth tokens, webhook secrets, cookies, SMTP or
  PocketBase credentials;
- payment details;
- full provider prompts/responses;
- customer identifiers when tenant/ticket IDs are sufficient.

Use stable correlation IDs, error categories, counts, durations, provider/request
IDs, and redacted field names. Debug content logging requires a time-bounded,
approved incident procedure and must be removed after use.

## 8. Deletion verification

A deletion or tenant purge is complete only when verification confirms:

- primary records are absent or anonymized as specified;
- attachment objects and derivatives are absent;
- retrieval/index results no longer return the content;
- caches and exports are removed;
- configured provider deletion completed or an exception is documented;
- active credentials are revoked;
- metrics/logs contain no prohibited content;
- backup expiry/replay treatment is recorded;
- a second authorized person or automated verifier reviewed the evidence for
  high-risk tenant deletions.

Deletion tests should use synthetic tenant data and cover a full tenant purge,
single-user/data-subject deletion, attachment deletion, knowledge-source removal,
and restore-after-deletion.

## 9. Legal hold

A legal hold requires:

- written reason and scope;
- authorized requester and approver;
- affected tenant/data classes;
- start date and review/expiry date;
- restricted access;
- notice to the customer where permitted/required;
- suspension only of the relevant deletion;
- audit event for creation, review, and release.

A legal hold must not silently disable all tenant retention.

## 10. Implementation readiness checklist

Before a real customer pilot:

- [ ] Customer-specific periods and deletion obligations are recorded.
- [ ] Every stored data class has an owner and deletion path.
- [ ] Ticket, attachment, knowledge, user, and tenant deletion are tested.
- [ ] Search/retrieval indexes are included in deletion.
- [ ] Logs and traces pass redaction tests.
- [ ] Backup retention and restore-time deletion replay are documented and tested.
- [ ] Provider/subprocessor retention and deletion behavior is recorded.
- [ ] Tenant export and termination procedures are exercised with synthetic data.
- [ ] Legal hold access and review process is assigned.
