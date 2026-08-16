# Data-processing overview for DACH deployments

Status: **Customer-facing technical draft; legal review required before contractual use**

Owner: Privacy/legal owner with engineering data-flow owner

This document describes how the current Mantly product can process data in a
hosted SaaS or customer-managed deployment. It is a technical transparency
record, not a legal conclusion that a deployment complies with the GDPR, the
Swiss Federal Act on Data Protection, sector regulation, employment rules, or a
customer contract.

## 1. Roles and deployment models

### Hosted SaaS

The customer normally determines why support data is processed, which mailboxes,
knowledge sources, runbooks, providers, users, retention periods, and actions are
configured. The customer is therefore expected to act as controller or the
corresponding responsible party for that processing. Mantly operates the service
on the customer's documented instructions and is expected to act as processor or
the corresponding service-provider role.

This role allocation must be confirmed in the customer agreement. Mantly may act
as an independent controller for narrowly scoped account administration,
security, fraud prevention, legal compliance, and its own billing records where
applicable. Those purposes and data must remain separated from customer support
content.

### Customer-managed on premises

The customer operates the application, storage, network, secrets, backup store,
and configured providers. Mantly may still process limited account, license,
support, or incident data when the customer contacts Mantly or when a commercial
license service is used. The exact support-access and telemetry boundary must be
stated in the contract and deployment record.

On-premises operation does not automatically mean that all data remains on the
customer's infrastructure: configured model, email, observability, payment, CRM,
or other providers can receive data. The customer-specific provider inventory is
a deployment requirement.

## 2. Processing purposes

Mantly may process customer data only for configured and documented purposes:

- receive and normalize support messages and attachments;
- identify the tenant, project, customer/contact, account, conversation, and
  ticket context;
- classify, route, prioritize, assign, and track support work;
- retrieve permitted policy, product, account, and operational knowledge;
- match and execute a published runbook within its permissions;
- draft, approve, send, and reconcile customer responses;
- perform explicitly permitted external-system actions;
- maintain audit, evaluation, security, reliability, and pilot evidence;
- provide user/account administration, billing, and licensed operation;
- detect abuse, security incidents, duplicate delivery, and service failure;
- back up and recover the service according to the documented retention period.

Customer content must not be used for unrelated advertising, sale of data, or
training a general model unless the customer has separately and validly approved
that purpose and the product implements the required control. The production
baseline assumes no such secondary use.

## 3. Data subjects

Depending on the customer and workflow, data can relate to:

- customer or prospective-customer contacts;
- customer employees, contractors, representatives, and account users;
- the customer's support agents, administrators, managers, and reviewers;
- suppliers, carriers, partners, and other third-party contacts appearing in a
  support case;
- individuals mentioned in attachments or knowledge sources;
- Mantly account, billing, security, and support contacts.

The customer must assess whether children, employees, patients, insured persons,
financial clients, or other protected/vulnerable groups are in scope.

## 4. Personal-data categories

The system can process:

- identity and contact data: names, email addresses, phone numbers, usernames;
- account and relationship data: tenant, organization, customer/account IDs,
  order or case references, memberships, roles;
- communication data: subjects, message bodies, quoted threads, signatures,
  timestamps, participants, channel metadata;
- attachment and document data: files, images, PDFs, extracted text/OCR, document
  metadata;
- operational data: ticket status, priority, assignee, queue, SLA, tags, notes,
  approvals, runbook/action state;
- external-system data returned by permitted tools, such as shipment or order
  status;
- knowledge and policy data uploaded or synchronized by the customer;
- AI data: selected context, prompt inputs, model outputs, provider/model
  identifiers, token and cost metadata;
- audit and security data: authentication events, object/action identifiers,
  request/correlation IDs, failures, IP/device data where logged, incident
  evidence;
- billing/license data: plan, usage totals, invoice/subscription identifiers,
  license status;
- customer feedback and evaluation outcomes.

Mantly does not require special-category or highly sensitive data for the V1
workflow. Such data can still appear in free-text messages or attachments. The
customer must identify that risk and configure minimization, redaction, provider,
retention, and human-review controls accordingly.

## 5. Data-flow map

```text
message sender
  -> configured email/channel provider
  -> Mantly channel connector/webhook/sync
  -> tenant-scoped ticket/message/attachment storage
  -> permitted retrieval and runbook runtime
       -> optional model provider
       -> optional customer/external tool provider
  -> approval where configured
  -> outbound queue
  -> originating channel/provider
  -> recipient

parallel operational flows:
  -> audit/evaluation/security telemetry
  -> optional approved observability provider
  -> encrypted off-host backup
  -> customer export/deletion workflow
```

### Ingestion

The channel adapter receives provider metadata and content, verifies the
configured channel binding, deduplicates source events/messages, and creates or
updates tenant-scoped records. Webhook signatures, replay protection, and
least-privilege channel credentials are required where supported.

### Storage

The current single-node architecture uses PocketBase/SQLite plus application data
volumes. PocketBase stores authentication and application records and can manage
files. The backend can also store application-managed data under `/app/data`.
Exact collection/field and attachment paths must be inventoried for the deployed
release.

### Model processing

Only context required for the configured task should be sent. Provider selection,
region, retention, training/use terms, credentials, and tenant permission must be
recorded. Model output is untrusted and cannot independently bypass deterministic
permissions, approval, schema, idempotency, or delivery controls.

### External actions

A runbook may call approved customer systems. The tool receives the minimum
required parameters and a tenant-scoped credential. Material actions require an
audit trail, idempotency, and the configured human-approval boundary. Financial,
destructive, or irreversible actions require human approval in the first pilot.

### Outbound delivery

The system queues the approved response with tenant/channel/conversation binding,
content/version reference, delivery attempts, and final status. Failed or unknown
provider outcomes remain visible for manual reconciliation.

### Telemetry and backup

Operational telemetry uses identifiers, categories, counts, and durations rather
than full content by default. Prompt/content tracing is disabled unless explicitly
approved. Encrypted backups contain the durable customer state and are subject to
restricted access, bounded retention, restore testing, and deletion replay.

## 6. Processing instructions and configuration ownership

Customer instructions should be represented by:

- selected tenant/project and users/roles;
- enabled channels and connector scopes;
- approved model/provider configuration;
- permitted knowledge sources and visibility;
- published runbook versions;
- allowed tools/actions and risk classes;
- autonomy, approval, and response policies;
- retention/deletion periods;
- localization and AI-disclosure settings;
- support, export, and incident contacts.

An instruction that would violate law, a contract, a security boundary, or the
product's deterministic safety control must be rejected or escalated rather than
silently executed.

## 7. International transfers and location

For every production deployment, complete the subprocessor/configuration inventory
with:

- legal entity and service;
- processing and storage locations;
- support/remote-access locations;
- data categories and purpose;
- controller/processor relationship;
- retention and model-training/use setting;
- transfer basis or adequacy position identified by qualified legal review;
- customer opt-out or regional alternative;
- deletion and incident-notification commitments.

Do not infer that an EU or Swiss endpoint means all support, telemetry, abuse
review, subprocessors, or backup data stays in that region. Obtain current
provider documentation and contract terms for the configured account.

## 8. Data minimization and purpose limitation

Required controls:

- choose the smallest mailbox, folder, project, knowledge corpus, and external
  permission scope;
- strip unrelated quoted history and attachment content when it is not required;
- avoid sending secrets, payment data, or complete account records to a model;
- use references rather than content in metrics, alerts, and operational tickets;
- separate product analytics from customer support content;
- keep debug/content tracing disabled by default;
- route unsupported or ambiguous requests to human handling rather than expanding
  context or permissions automatically;
- review fields, prompts, tools, and logs whenever the V1 workflow changes.

## 9. Retention, deletion, and export

The technical baseline is in:

- `docs/security/data-retention.md`;
- `docs/compliance/data-export-and-tenant-deletion.md`;
- `docs/operations/backup-and-recovery.md`.

Customer-specific periods and legal obligations must be approved before go-live.
Deletion includes primary records, files, derived extraction/index data, caches,
exports, configured provider copies where controllable, and restore-time replay
against older backups. A minimized deletion receipt can remain when required for
security/accountability.

## 10. Security and confidentiality

The current technical baseline includes:

- authentication plus tenant/project/object authorization;
- role and runbook/tool permission enforcement;
- untrusted-content and prompt-injection boundaries;
- idempotent, claimed/fenced external actions and outbound delivery;
- encrypted transport and protected secrets;
- structured/redacted logging;
- vulnerability reporting and incident response;
- dependency, secret, and configuration scanning;
- encrypted, verified backup and restore;
- staged human review and safe manual fallback.

See `SECURITY.md` and `docs/security/threat-model.md`. A deployment-specific
security questionnaire must link each customer claim to configuration, test,
workflow, or contractual evidence.

## 11. AI transparency and human control

Before using automatic or assisted responses, the customer decides:

- whether and how end users are informed that AI assisted or generated a response;
- which runbooks may draft, act, send, or require approval;
- which decisions are excluded from automation;
- the human escalation, contest, correction, and complaint path;
- review sampling and pause conditions;
- allowed providers and data regions;
- whether prompt/response traces are retained.

Mantly should record the runbook/model/provider and human-touch/approval status
without exposing hidden prompts or unrelated data. A customer-visible response
must not misrepresent a material automated decision as a human review when none
occurred.

## 12. Data-subject and customer requests

The customer remains responsible for identifying the applicable request and
verifying the requester. Mantly must support the customer's process for:

- access/export;
- correction;
- deletion or restriction;
- objection/opt-out where applicable;
- human review/contest of an automated outcome;
- incident inquiry;
- tenant termination and return/deletion of data.

The operational procedure must search all configured data stores/providers and
record exceptions where deletion or disclosure is legally restricted.

## 13. Incident and breach support

Mantly's incident runbook requires early severity declaration, containment,
evidence preservation, affected-data/tenant assessment, provider coordination,
recovery, and accurate customer updates. Contractual responsibilities must define:

- security contact and 24/7 escalation path;
- notification trigger and timeline;
- evidence and cooperation scope;
- subprocessor notification relay;
- responsibility for authority/data-subject communications;
- post-incident report and corrective actions.

Technical incident detection is not itself a legal breach determination; that
assessment requires the responsible privacy/legal owner.

## 14. Hosted/on-prem responsibility matrix

| Control | Hosted SaaS | Customer-managed on premises |
| --- | --- | --- |
| Host/network/container security | Mantly | Customer |
| Application security fixes | Mantly | Mantly supplies; customer deploys within agreed time |
| Customer user/role/runbook configuration | Customer | Customer |
| Mantly infrastructure secrets | Mantly | Not applicable/customer for local secrets |
| Customer connector/provider credentials | Shared configuration responsibility | Customer |
| Model/provider choice and data region | Shared; customer instruction plus Mantly-supported options | Customer, within supported options |
| Backup execution/storage | Mantly | Customer |
| Restore drill | Mantly | Customer with Mantly support as agreed |
| Retention/deletion configuration | Shared | Customer |
| Customer request verification | Customer | Customer |
| Security monitoring/incident response | Mantly, with customer cooperation | Customer infrastructure; shared product support as agreed |
| Subprocessor contract | Mantly for SaaS subprocessors | Customer for directly configured providers; Mantly for its separate services |
| Legal basis and notices for support processing | Customer | Customer |

The contract can allocate responsibilities differently. The customer-specific
record is authoritative.

## 15. Pre-pilot approval checklist

- [ ] Controller/processor and independent-controller purposes reviewed.
- [ ] Data subjects, categories, special/high-risk data, and workflow documented.
- [ ] Hosted/on-prem responsibility matrix completed.
- [ ] Configured providers/subprocessors and locations approved.
- [ ] International-transfer assessment completed where required.
- [ ] DPA and security schedule reviewed by qualified legal/security owners.
- [ ] Retention, deletion, export, backup, and termination periods approved.
- [ ] Model data-use/training and tracing settings confirmed.
- [ ] AI transparency, human review, contest, and escalation behavior approved.
- [ ] Incident contacts and notification duties recorded.
- [ ] Synthetic export/deletion/restore-after-deletion exercise passed.
- [ ] Claims in the customer questionnaire link to current evidence.
- [ ] No document claims certification or legal compliance that has not been independently established.
