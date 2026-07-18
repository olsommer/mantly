# DPA and security-schedule checklist

Status: **Negotiation checklist; qualified legal review required**

This checklist helps product, engineering, security, and legal owners verify that
the contract matches the configured deployment. It is not a contract template and
does not replace legal advice.

## 1. Parties and roles

- [ ] Contracting legal entities and addresses are correct.
- [ ] Customer/controller or responsible-party role is stated for support data.
- [ ] Mantly's processor/service-provider role is stated for hosted processing.
- [ ] Any independent-controller purposes are narrow and explicit, such as account
  administration, security, legal compliance, and billing.
- [ ] On-premises support, license-validation, remote-access, and telemetry roles
  are stated separately.
- [ ] Customer affiliates, projects, and authorized users are in scope or excluded.

## 2. Documented instructions and scope

- [ ] Subject matter and duration of processing are defined.
- [ ] Nature and purposes match `data-processing-overview.md` and the active V1 workflow.
- [ ] Data-subject and data-category descriptions are accurate for the customer.
- [ ] Special-category/high-risk data is prohibited, minimized, or specifically controlled.
- [ ] Enabled channels, providers, knowledge sources, tools, and runbooks are recorded.
- [ ] Model/provider choice, region, retention, and training/use setting are instructions.
- [ ] New purpose, provider, or high-risk action requires customer instruction/approval.
- [ ] Unlawful or unsafe instructions can be rejected and escalated.

## 3. Confidentiality and personnel

- [ ] Access is limited to authorized personnel with confidentiality obligations.
- [ ] Production, support, incident, and backup access roles are defined.
- [ ] Privileged access is logged and periodically reviewed.
- [ ] Customer-content access for support requires a ticket/incident purpose and approval.
- [ ] Background checks or training commitments are stated only when actually implemented.
- [ ] Remote-access countries/locations are included in the provider inventory.

## 4. Technical and organizational measures

The security schedule should link to current evidence for:

- [ ] tenant/project/object authorization;
- [ ] authentication, password reset, session, and admin controls;
- [ ] encryption in transit and backup encryption at rest;
- [ ] secret management and rotation;
- [ ] vulnerability/dependency/secret/configuration scanning;
- [ ] secure development, code review, CI, and release integrity;
- [ ] prompt injection, untrusted content, SSRF, and tool-output controls;
- [ ] runbook/tool permissions, approval, idempotency, and action fencing;
- [ ] outbound delivery claim, retry, unknown-outcome, and reconciliation controls;
- [ ] structured/redacted logs and restricted tracing;
- [ ] backup, restore, RPO/RTO, and restore drills;
- [ ] incident response, evidence preservation, and recovery;
- [ ] retention, deletion, export, and tenant termination;
- [ ] business continuity and the current single-node limitation;
- [ ] regular testing and review cadence.

Do not promise a certification, penetration-test cadence, availability level,
RPO/RTO, or encryption mode that the deployed service does not meet.

## 5. Subprocessors and providers

- [ ] Customer-specific inventory was created from `subprocessors.example.json`.
- [ ] Legal entity, service, purpose, data, locations, support access, retention,
  transfer basis, deletion, and incident terms are complete.
- [ ] Required and optional providers are distinguished.
- [ ] Customer-direct providers are distinguished from Mantly subprocessors.
- [ ] Notice/objection process and timing are negotiated.
- [ ] Mantly remains responsible for contracted subprocessors to the extent required.
- [ ] Provider changes cannot silently expand purpose, data, or location.
- [ ] Provider failure/termination and data return/deletion are addressed.

## 6. International transfers

- [ ] Processing and support-access locations are known for every provider.
- [ ] Applicable adequacy, contractual safeguards, or other transfer mechanism is
  selected by qualified legal review.
- [ ] Required transfer-impact or country-risk assessment is completed.
- [ ] Supplementary technical/organizational measures are documented.
- [ ] Government/law-enforcement request handling is addressed where relevant.
- [ ] Customer is told when a configured provider changes the transfer position.

## 7. Security incidents and personal-data breaches

- [ ] Security contact and 24/7 escalation path are current.
- [ ] Contract distinguishes a security incident from the customer's legal breach determination.
- [ ] Notification trigger and timing are realistic and support downstream duties.
- [ ] Notification content includes known scope, data, subjects, consequences,
  containment, mitigation, and contact information as applicable.
- [ ] Subprocessor notifications flow promptly to Mantly and the customer.
- [ ] Evidence/cooperation, forensic boundaries, and cost allocation are addressed.
- [ ] Customer/public/authority communications and approvals are allocated.
- [ ] Post-incident report and corrective-action process are included.

## 8. Data-subject and regulatory assistance

- [ ] Customer verifies and directs requests; Mantly does not independently decide the legal response.
- [ ] Access, export, correction, deletion, restriction, objection, and human-review assistance are covered.
- [ ] Response procedures include all configured stores, indexes, providers, exports, and backups.
- [ ] Regulatory inquiries, audits, and impact assessments have a scoped assistance process.
- [ ] Assistance fees or limits do not prevent required cooperation.
- [ ] Mantly notifies the customer when it receives a request relating to customer data unless prohibited.

## 9. Retention, deletion, return, and termination

- [ ] Customer-specific retention periods are attached or configurable.
- [ ] Ticket, attachment, knowledge, logs, traces, audit, metrics, billing, incident,
  and backup periods are distinguished.
- [ ] Data return/export format and timing are defined.
- [ ] Tenant termination disables access/connectors/automation at the agreed time.
- [ ] Deletion includes primary and derived/index/cache/provider data under control.
- [ ] Backup expiry and restore-time deletion replay are explained.
- [ ] Legally retained data and legal holds are narrowly scoped and disclosed as permitted.
- [ ] Deletion confirmation/evidence is defined without retaining deleted content.

## 10. Audit and assurance

- [ ] Customer assurance needs are proportionate to the service and risk.
- [ ] Standard evidence package is defined: policies, architecture, scans, tests,
  restore drill, incident tabletop, subprocessor list, and recent security review.
- [ ] Audit notice, confidentiality, scope, frequency, and production-safety rules are defined.
- [ ] Existing independent reports can satisfy overlapping requests where appropriate.
- [ ] Remediation findings have severity, owner, due date, and customer communication rules.
- [ ] No right requires disclosing another tenant's data, sensitive exploit details,
  or unrelated proprietary information.

## 11. AI-specific terms

- [ ] Approved model providers/models and data-use terms are recorded.
- [ ] Customer content is excluded from general training/secondary use unless separately approved.
- [ ] Human-review and prohibited-decision boundaries are documented.
- [ ] AI disclosure/transparency configuration is allocated to the customer.
- [ ] Customer has a contest/correction/escalation path.
- [ ] Material provider/model changes follow change-management rules.
- [ ] Token/cost and operational metrics do not become a content replica.
- [ ] The agreement does not promise deterministic model accuracy; it promises
  controls, review, evidence, and incident handling that are actually implemented.

## 12. Liability, service levels, and commercial boundary

- [ ] Security/privacy obligations align with liability and insurance terms.
- [ ] Availability, support, RPO/RTO, and response-time commitments match the current architecture.
- [ ] Pilot commitments are distinguished from general-availability commitments.
- [ ] Customer configuration failures and unsupported modifications are addressed without eliminating Mantly's own responsibility.
- [ ] On-premises patch/deployment responsibility and support window are explicit.
- [ ] License validation or service termination cannot make customer data inaccessible without an agreed export/recovery path.

## 13. Approval record

| Review | Owner | Version/date | Decision | Open items |
| --- | --- | --- | --- | --- |
| Product scope | TBD | TBD | approve/reject | TBD |
| Engineering/data flow | TBD | TBD | approve/reject | TBD |
| Security | TBD | TBD | approve/reject | TBD |
| Privacy/legal | TBD | TBD | approve/reject | TBD |
| Customer privacy/legal | TBD | TBD | approve/reject | TBD |
| Customer security/procurement | TBD | TBD | approve/reject | TBD |

No customer pilot should rely on this checklist alone. The executed agreement and
approved deployment record are authoritative.
