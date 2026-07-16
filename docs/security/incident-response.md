# Security incident response

Status: **Production runbook**

Owner: Incident commander assigned at incident declaration

This runbook covers suspected or confirmed compromise of Mantly, its deployment,
its providers, or customer data. It must be adapted with real contact details,
customer notification obligations, and infrastructure access procedures before a
production-like pilot.

## 1. When to declare an incident

Declare an incident when there is credible evidence of:

- cross-tenant access or disclosure;
- unauthorized account, admin, service, or infrastructure access;
- exposed credentials, secrets, signing material, or backup keys;
- unauthorized financial, destructive, customer-visible, or irreversible action;
- duplicate side effects with customer or business impact;
- malware, malicious attachment processing, remote code execution, or SSRF;
- material prompt injection that bypassed policy or action controls;
- loss, corruption, or unexplained disappearance of tickets, actions, or audit data;
- model/provider, email, CRM, Stripe, or other subprocessor compromise affecting Mantly data;
- availability failure that breaches the agreed service or pilot boundary;
- inability to reconstruct a material automated decision because required audit evidence is missing;
- a vulnerability believed to be under active exploitation.

When uncertain, declare early and downgrade later.

## 2. Severity levels

### SEV-0 — Critical security incident

Examples:

- confirmed tenant-isolation failure;
- active unauthorized access to production data;
- leaked production superuser/JWT/tool credentials with plausible use;
- unauthorized destructive or financial action;
- active remote code execution;
- widespread data corruption or unrecoverable loss;
- active exploitation affecting customers.

Response: immediate containment, executive/customer owner involvement, continuous coordination until stable.

### SEV-1 — High-impact incident

Examples:

- limited unauthorized disclosure;
- compromised non-global credential;
- repeatable prompt/tool-control bypass without confirmed exploitation;
- duplicate customer-visible action;
- critical service unavailable with material ticket impact;
- backup or recovery failure that materially increases exposure.

Response: urgent same-day containment and investigation.

### SEV-2 — Moderate incident

Examples:

- security control failed but compensating control prevented customer impact;
- limited availability or queue backlog;
- provider misconfiguration with no evidence of disclosure;
- missing non-critical telemetry or delayed audit data.

Response: business-day triage and tracked remediation.

### SEV-3 — Low-impact event

Examples:

- policy or hygiene issue with no plausible immediate exploit;
- blocked attack attempt;
- minor security-documentation or monitoring gap.

Response: normal maintenance with an owner and due date.

## 3. Roles

One person may hold several roles in an early-stage incident, but each role must be explicit.

| Role | Responsibility |
| --- | --- |
| Incident commander | Owns severity, priorities, decisions, cadence, and closure |
| Technical lead | Investigation, containment, eradication, recovery |
| Security/privacy lead | Evidence handling, exposure assessment, notification analysis |
| Customer/comms lead | Accurate customer, partner, and internal updates |
| Scribe | Timestamped decision, action, evidence, and status log |
| Business owner | Accepts customer/business trade-offs and continuity decisions |

The incident commander is not required to be the most senior person. They must be
available and able to coordinate.

## 4. Immediate response checklist

### First 15 minutes for SEV-0/SEV-1

- [ ] Start a private incident record with UTC timestamps.
- [ ] Assign incident commander, technical lead, security/privacy lead, and scribe.
- [ ] Record detection source, affected environment, suspected tenants, and current impact.
- [ ] Preserve relevant logs, audit records, request IDs, deployment commit, configuration version, and provider events.
- [ ] Disable the smallest affected path that safely stops further harm:
  - runbook;
  - connector/tool;
  - provider;
  - tenant;
  - outbound delivery;
  - public endpoint;
  - entire deployment.
- [ ] Revoke or rotate exposed credentials without destroying evidence of their use.
- [ ] Stop automatic deletion, log rotation, and mutable cleanup that could remove evidence.
- [ ] Confirm that containment did not create a larger integrity or availability failure.

### First hour

- [ ] Establish a working incident timeline.
- [ ] Identify the earliest known indicator and current blast radius.
- [ ] Determine whether cross-tenant exposure is possible.
- [ ] Determine whether actions were attempted, completed, duplicated, or left in unknown state.
- [ ] Identify affected data categories, systems, providers, users, and jurisdictions.
- [ ] Preserve copies of relevant infrastructure/application/provider logs with access restricted.
- [ ] Contact affected provider security channels where required.
- [ ] Decide internal and customer update cadence.
- [ ] Begin legal/privacy notification analysis; do not speculate in customer communications.

## 5. Containment playbooks

### Suspected credential exposure

1. Identify credential type, scope, environment, tenant, and last known valid use.
2. Disable or rotate it immediately when safe.
3. Search logs/provider consoles for anomalous use before and after rotation.
4. Rotate dependent credentials if the exposed secret could reveal or mint them.
5. Invalidate sessions/tokens derived from the secret.
6. Confirm applications and workers use the new value.
7. Record why the credential was exposed and how recurrence will be prevented.

### Tenant-isolation or authorization failure

1. Disable the affected endpoint, role, object type, or tenant-facing path.
2. Preserve access logs and request correlation IDs.
3. Identify all objects reachable through the same authorization path.
4. Test across at least two controlled tenants before re-enabling.
5. Review exports, attachments, audit APIs, admin endpoints, and side-effecting tools for the same pattern.
6. Require explicit engineering and security approval to restore the path.

### Unauthorized or duplicate external action

1. Disable the affected runbook/tool and pause outbound delivery if messaging could compound harm.
2. Determine provider-side truth; distinguish failed, succeeded, duplicated, and unknown outcomes.
3. Do not blindly replay the action or the whole ticket.
4. Execute rollback or compensation only when the external contract supports it and approval is recorded.
5. Contact the operational/customer owner to coordinate customer remediation.
6. Preserve idempotency keys, claim/fencing state, provider request IDs, and responses.

### Prompt injection or poisoned knowledge

1. Pause affected runbooks and knowledge sources.
2. Preserve source message/document, retrieval evidence, prompt structure, model/provider identity, and output.
3. Determine whether secrets, unrelated tenant data, or unauthorized tool calls were exposed.
4. Remove or quarantine the source only after evidence preservation.
5. Add a regression fixture and strengthen deterministic policy controls before re-enabling.

### Data corruption or loss

1. Stop writes if continued operation can expand corruption.
2. Preserve primary storage and logs before repair attempts.
3. Identify the last known good backup and expected RPO/RTO.
4. Restore into an isolated environment first.
5. Verify tenant, ticket, message, attachment, action, delivery, knowledge, and audit integrity.
6. Reconcile transactions/events after the restore point.
7. Reopen production only after business and technical approval.

### Provider/subprocessor incident

1. Confirm affected service, region, data categories, and time window.
2. Disable or switch provider when contract and architecture allow.
3. Rotate provider credentials if compromise is possible.
4. Obtain provider incident evidence and reference numbers.
5. Determine whether Mantly data was retained, disclosed, corrupted, or unavailable.
6. Include the provider in customer notification and post-incident evidence as appropriate.

## 6. Evidence handling

- Store evidence in a restricted incident location, not in public issues or normal application logs.
- Record original source, collector, UTC time, hash where practical, and any transformation/redaction.
- Avoid copying complete customer datasets when a scoped export proves the issue.
- Redact secrets and unrelated personal data from working notes and customer communications.
- Preserve deployment commit, container image digest, configuration version, database/backup identifiers, and provider model/version.
- Do not alter production records solely to make the incident easier to explain.

## 7. Communications

### Internal status format

```text
Severity / incident ID:
Current impact:
Affected tenants/workflows:
Known start time:
Containment status:
Data/action exposure assessment:
Next actions and owners:
Decision needed:
Next update time:
```

### Customer communication principles

- State confirmed facts, affected service/data, protective action, and next update.
- Separate confirmed impact from investigation scope.
- Do not promise that no data was accessed unless evidence supports it.
- Include concrete customer action only when required, such as password reset or key rotation.
- Coordinate legally required notification with qualified privacy/legal owners.
- Record all versions and recipients of incident communications.

## 8. Eradication and recovery

Before restoring normal operation:

- root cause and exploit path are understood enough to prevent immediate recurrence;
- affected credentials are rotated and sessions invalidated;
- malicious persistence and unauthorized changes are removed;
- regression tests cover the failure path;
- restored or repaired data passes integrity checks;
- paused runbooks/connectors are reviewed and explicitly republished/re-enabled;
- monitoring and alerting can detect recurrence;
- operational owner accepts any residual risk;
- customer-facing recovery steps are complete or tracked.

Use gradual restoration where possible:

1. read-only/admin verification;
2. manual ticket handling;
3. assisted/draft behavior;
4. limited automatic behavior;
5. normal approved autonomy.

## 9. Closure criteria

An incident can close when:

- containment, eradication, and recovery are complete;
- affected customers and authorities have received required communications;
- all unknown action/delivery states are reconciled or explicitly accepted;
- evidence and timeline are complete;
- follow-up work has owners, severity, and due dates;
- temporary mitigations have expiry/review dates;
- the incident commander, technical lead, and security/privacy lead approve closure.

## 10. Post-incident review

Hold the review within five business days for SEV-0/SEV-1 and ten business days
for SEV-2.

The review must include:

- executive summary and customer impact;
- detailed timeline;
- detection and response effectiveness;
- technical and organizational root causes;
- contributing conditions;
- what limited the blast radius;
- what delayed containment or recovery;
- data/action exposure assessment;
- evidence and confidence limitations;
- corrective actions with owners and deadlines;
- required updates to threat model, tests, monitoring, deployment, runbooks,
  retention, and training.

Do not treat “human error” as a complete root cause. Identify the system condition
that allowed one action to create the incident.

## 11. Required local customization before pilot

- [ ] Add real primary and backup incident contacts.
- [ ] Add customer-contract notification contacts and timelines.
- [ ] Add infrastructure, PocketBase, DNS, SMTP, Stripe, model-provider, and email-provider emergency access procedures.
- [ ] Add credential rotation commands/links for every production secret class.
- [ ] Add provider security contact and account identifiers.
- [ ] Add the approved private evidence location.
- [ ] Exercise a tabletop scenario for tenant isolation, credential exposure, and duplicate external action.
- [ ] Record the date, participants, gaps, and remediation from the tabletop.
