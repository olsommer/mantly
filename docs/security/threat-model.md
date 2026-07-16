# Mantly threat model

Status: **Required for production-like pilots**

Owner: Engineering security owner

Review triggers:

- a new channel, model provider, data store, or side-effecting connector;
- a change to tenant/project authorization;
- a new autonomous action class;
- a security incident or material penetration-test finding;
- at least every six months while the product is active.

## 1. Scope

This threat model covers the hosted SaaS and customer-managed on-premises
deployments described in this repository. It focuses on the pilot-critical path:

```text
customer email
  -> channel ingestion/webhook or sync
  -> ticket and attachment storage
  -> runbook match and knowledge retrieval
  -> model/provider call
  -> tool/action execution
  -> human approval where configured
  -> outbound delivery
  -> audit, analytics, and backup
```

It does not claim that every future channel or connector is covered. A new trust
boundary requires an update before production use.

## 2. Security objectives

Mantly must preserve:

- **tenant isolation:** one tenant cannot read, influence, or act on another
  tenant's data;
- **authorization:** users, service identities, runbooks, and tools receive only
  the permissions they require;
- **action integrity:** side effects occur only when an approved runbook and
  policy allow them, at most once for one logical request;
- **confidentiality:** messages, attachments, knowledge, credentials, and traces
  are not exposed to unauthorized parties or providers;
- **auditability:** material decisions, approvals, actions, failures, and
  deliveries can be reconstructed;
- **availability and recoverability:** failures are visible, contained, and
  recoverable without silent ticket loss;
- **safe degradation:** uncertainty or technical failure routes work to a human
  instead of expanding autonomy.

## 3. Assets

| Asset | Impact if compromised |
| --- | --- |
| Customer messages and attachments | Personal, contractual, financial, or commercially sensitive data exposure |
| Tenant configuration and policies | Incorrect or unauthorized support behavior |
| Runbooks and published versions | Unauthorized automation or policy bypass |
| Knowledge sources and retrieval index | Confidential-data exposure or poisoned answers |
| User and service credentials | Account takeover, cross-system access, persistent compromise |
| Model-provider/API keys | Cost abuse, provider-data exposure, service disruption |
| Tool/connector credentials | Unauthorized business actions in external systems |
| Ticket/action/delivery state | Duplicate, missing, or misleading customer outcomes |
| Audit and evaluation history | Loss of accountability and inability to investigate incidents |
| Billing/license configuration | Revenue loss, tenant entitlement bypass, service disruption |
| Backups | Bulk historical-data exposure and recovery compromise |

## 4. Actors

- unauthenticated internet attacker;
- malicious or compromised tenant user;
- honest tenant user with excessive permissions;
- malicious message sender or attachment author;
- compromised email/channel/provider account;
- compromised model or connector provider;
- operator or maintainer error;
- malicious insider with infrastructure or PocketBase access;
- attacker with a leaked webhook, API, JWT, SMTP, Stripe, model, or tool secret;
- another tenant attempting cross-tenant access;
- automated abuse causing cost or availability exhaustion.

## 5. Trust boundaries

### 5.1 Public internet to Caddy/FastAPI/PocketBase

Untrusted requests enter through public routes, authentication endpoints,
webhooks, add-in/admin traffic, and PocketBase proxy routes.

Required controls:

- TLS at the deployment edge;
- explicit CORS origins in authenticated deployments;
- rate limits on authentication, expensive, and public endpoints;
- strict request-size and attachment-size limits;
- security response headers;
- no direct public exposure of internal-only service ports;
- production demo endpoints disabled;
- consistent authentication and authorization before tenant data access.

Verification:

- deployment smoke tests;
- unauthorized and cross-tenant integration tests;
- route inventory review;
- external attack-surface scan before a customer pilot.

### 5.2 User/session identity to tenant/project authorization

Authentication proves an identity; every data operation must still enforce the
current tenant, project, role, and object-level permission.

Threats:

- insecure direct object reference;
- relying on client-supplied tenant/project IDs;
- admin-only routes reachable by non-admin users;
- stale privileges after role or tenant changes;
- service tokens with global access used in tenant-facing code.

Required controls:

- derive tenant/project scope from the authenticated principal;
- validate object membership on every read and write;
- centralize authorization helpers and avoid UI-only checks;
- separate PocketBase superuser operations from tenant-facing paths;
- revoke or refresh sessions after material privilege changes;
- test reads, writes, deletes, exports, attachments, and side effects across two
  tenants.

### 5.3 Untrusted message/attachment content to agent and retrieval runtime

Email bodies, quoted threads, signatures, HTML, links, files, OCR output, and
retrieved documents are untrusted data. They can contain prompt injection,
malware, misleading instructions, or poisoned policy content.

Threats:

- instructions that tell the model to ignore system or runbook constraints;
- hidden text or attachment content requesting secret disclosure;
- malicious links causing server-side requests;
- active content rendered in the admin UI;
- oversized or adversarial files causing resource exhaustion;
- retrieved documents that impersonate authoritative policy.

Required controls:

- never interpret customer content as system or tool policy;
- separate trusted instructions from untrusted content in prompts and runtime
  structures;
- sanitize rendered HTML and prohibit script execution;
- enforce file type, size, decompression, and processing limits;
- scan or quarantine files according to deployment risk;
- restrict URL fetches to approved schemes, hosts, IP ranges, sizes, redirects,
  and timeouts;
- mark source provenance and trust level;
- require human review or safe no-op behavior when evidence conflicts;
- never expose credentials, hidden prompts, or unrelated tenant context to the
  model.

Verification:

- prompt-injection and phishing test suites;
- malicious HTML/attachment fixtures;
- SSRF tests covering loopback, link-local, private networks, redirects, and DNS
  rebinding protections;
- retrieval provenance tests.

### 5.4 Mantly to model providers

A model-provider call can expose ticket content, retrieved knowledge, tool
results, metadata, and identifiers.

Threats:

- sending more customer data than required;
- using a provider or region not approved by the tenant;
- provider retention/training settings inconsistent with the contract;
- logging prompts or responses with secrets/customer content;
- model output causing unauthorized actions;
- token/cost abuse.

Required controls:

- tenant/provider policy and explicit provider selection;
- data minimization and redaction before provider calls;
- no secrets in prompts;
- documented provider region, retention, and subprocessor status;
- output treated as untrusted proposal until policy and schema validation pass;
- per-tenant/request budgets, timeouts, and retry limits;
- model/provider identity, token usage, and cost recorded without copying full
  content into metrics;
- bring-your-own-key isolation where supported.

### 5.5 Runbook runtime to tools and external systems

Tools can change orders, addresses, refunds, cases, subscriptions, or other
business state.

Threats:

- tool called without the required runbook or user permission;
- model chooses arbitrary parameters or endpoint;
- duplicate action after retry, replay, or concurrent scheduler execution;
- partial success followed by misleading failure;
- irreversible or financial action without approval;
- confused-deputy use of a credential belonging to another tenant;
- tool response containing prompt injection or secrets.

Required controls:

- allowlisted tool registry and typed input/output schemas;
- tenant-scoped credentials and explicit runbook permission;
- deterministic policy validation outside the model;
- idempotency key derived from tenant, ticket, runbook version, action, and
  logical operation;
- atomic claim/fencing before side effects;
- bounded retry policy that distinguishes safe retry from unknown outcome;
- approval for high-risk, financial, destructive, or irreversible actions;
- before-state and reversibility/compensation metadata where supported;
- stop automation and route manual on ambiguous or partial result;
- sanitize and classify tool output before feeding it back into a model.

Action risk classes:

| Class | Examples | V1 default |
| --- | --- | --- |
| Read-only | Shipment lookup, policy lookup | May run automatically when tenant-scoped |
| Reversible low-risk | Add internal note, open non-financial case | Automatic or approval based on runbook |
| Customer-visible | Send message, change delivery instruction | Idempotent; explicit response/action policy |
| Financial/destructive | Refund, cancel contract/order, delete data | Human approval required in first pilot |
| Irreversible/high-impact | Legal notice, payout, identity/account change | Disabled unless separately reviewed and approved |

### 5.6 Inbound webhooks and channel sync

Threats:

- forged webhook;
- replayed event;
- reordered or duplicated delivery;
- cursor manipulation causing data loss;
- channel account connected to the wrong tenant;
- webhook secret leakage.

Required controls:

- provider signature and timestamp verification;
- replay window and durable event/message deduplication;
- tenant/channel binding resolved from server-side configuration;
- monotonic cursor/checkpoint handling with visible lag/failure;
- least-privilege channel scopes;
- secret rotation procedure;
- raw event retention minimized and permission controlled.

### 5.7 Outbound queue and delivery

Threats:

- duplicate customer response;
- sending an unapproved or stale draft;
- delivering to the wrong conversation/customer;
- retries after an unknown provider outcome;
- queue item disappearing without final state.

Required controls:

- immutable content/version reference at approval time;
- tenant/channel/conversation binding revalidated before send;
- atomic claim and fencing token;
- idempotency key where provider supports it;
- explicit `queued`, `claimed`, `sent`, `delivered`, `failed`, and `manual review`
  states;
- retry only when the previous outcome is known safe;
- dead-letter/manual recovery path;
- complete attempt history.

### 5.8 Background schedulers and multiple instances

Threats:

- the same scheduler runs on multiple API replicas;
- duplicate delivery, CRM sync, SLA escalation, or automated action;
- lost work on process restart;
- in-memory state treated as durable.

Required controls:

- current single-instance limitation documented until distributed safety is
  proven;
- durable leases/claims and fencing for work that can cause side effects;
- heartbeat and last-success metrics;
- no correctness dependency on in-memory scheduler state;
- explicit deployment guard preventing unsupported multi-instance operation.

### 5.9 PocketBase/SQLite and application data volumes

Threats:

- direct superuser access bypasses tenant controls;
- SQLite corruption or unsafe concurrent access;
- data volume exposed through host permissions;
- migration destroys or changes authorization rules;
- attachment path traversal or insecure file serving.

Required controls:

- internal-network exposure only;
- strong unique superuser credentials stored outside the repository;
- production host and volume access restricted;
- schema and migration tests on clean and representative existing data;
- integrity checks and verified backups;
- attachment IDs resolved through authorized application paths;
- storage limits and monitoring;
- documented single-node capacity and migration path.

### 5.10 Admin UI and Outlook add-in

Threats:

- cross-site scripting from customer content;
- token leakage through URLs, logs, browser storage, or iframe messaging;
- clickjacking or overly broad frame policy;
- add-in running against the wrong API/tenant;
- unsafe copy/paste or rendered links;
- privileged UI action without server authorization.

Required controls:

- React escaping plus explicit sanitization for rendered HTML;
- no secrets in query strings;
- strict origin checks for `postMessage` and add-in integration;
- short-lived/authenticated sessions and secure reset flows;
- server-side authorization for every action;
- safe link handling and attachment download headers;
- content security policy compatible with the add-in deployment model;
- production builds disable mock/demo functionality.

### 5.11 Audit, analytics, traces, and logs

Threats:

- customer content, tokens, or secrets copied into logs;
- audit records altered or deleted by normal users;
- missing correlation prevents incident reconstruction;
- model traces sent to an unapproved observability provider;
- metric datasets become a shadow copy of support content.

Required controls:

- structured, redacted telemetry;
- stable correlation IDs for tenant/project/ticket/run/action/delivery;
- separate immutable or append-oriented audit semantics for material events;
- restricted trace-provider configuration and documented data flow;
- metrics contain references and classifications, not full message bodies;
- retention and access controls by data class;
- tests for redaction of credentials and common personal-data fields.

### 5.12 Backups and recovery

Threats:

- unencrypted backup copied off-host;
- backup includes live secrets or is broadly accessible;
- tenant deletion not reflected in retained backups;
- backup exists but cannot be restored;
- ransomware or operator error affects both primary data and backup.

Required controls:

- encrypted backup at rest and in transit;
- separate access boundary from production host;
- integrity manifest and timestamp;
- documented retention and deletion treatment;
- restore into a clean environment with automated verification;
- periodic restore drill;
- no claim of point-in-time recovery unless implemented and tested.

## 6. Abuse and availability threats

Mantly can incur model, attachment-processing, email, and external API costs.
Controls must include:

- per-user, tenant, route, and provider rate limits;
- request, file, extraction, context, token, and tool-call budgets;
- bounded concurrency and queue depth;
- circuit breakers for failing providers;
- cancellation/timeouts for long-running work;
- quotas and alerting before hard exhaustion;
- manual disable switches for a tenant, runbook, connector, and provider;
- protection against recursive or self-triggering message loops.

## 7. Secret management

Secrets include JWT keys, PocketBase superuser credentials, SMTP credentials,
Stripe keys, model keys, webhook secrets, connector tokens, license signing
material, and backup encryption keys.

Requirements:

- secrets are injected through the deployment secret store or environment, never
  committed;
- production secrets are unique per environment and tenant where applicable;
- logs and exception messages redact secret values;
- rotation is documented and tested for each secret class;
- suspected exposure triggers immediate revocation/rotation and incident review;
- backup encryption keys are separated from the backups;
- local `.env`/`config.env` files and exported credentials remain ignored.

## 8. Security verification matrix

| Boundary | Minimum verification before pilot |
| --- | --- |
| Authentication and authorization | Admin/non-admin tests, cross-tenant CRUD and attachment tests |
| Message/attachment input | Prompt-injection, phishing, HTML sanitization, file limit tests |
| Webhooks/channel sync | Signature, replay, duplicate, wrong-tenant tests |
| Runbook/tool actions | Permission, schema, approval, idempotency, partial failure tests |
| Outbound delivery | Atomic claim, duplicate send, retry/unknown outcome tests |
| Logging/tracing | Secret and content redaction tests |
| Storage/migrations | Clean bootstrap, existing-data migration, restore verification |
| Deployment | Auth/CORS/demo flags, internal ports, TLS, health checks |
| Dependencies/secrets | Automated pull-request scanning |

## 9. Residual risk and production acceptance

Before a real customer pilot, unresolved high/critical findings require a written
risk acceptance containing:

- affected asset and tenant/workflow;
- exploit scenario and impact;
- current mitigation;
- owner;
- expiry date;
- operational detection;
- rollback/disable procedure;
- explicit approval by engineering and the accountable business owner.

A risk acceptance is not permanent. Critical tenant-isolation, unauthorized
financial/destructive action, or known active-exploitation risk is not acceptable
for production-like pilot traffic.
