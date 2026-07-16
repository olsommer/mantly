# Customer security and privacy evidence index

Status: **Answer framework; complete per deployment and customer**

This document prevents unsupported questionnaire claims. Replace every
`customer-specific` value and attach current evidence before sending it to a
customer, auditor, or procurement team.

## Product and scope

| Question | Standard answer boundary | Evidence |
| --- | --- | --- |
| What does Mantly process? | Customer support messages, attachments, operational context, permitted knowledge, runbook/action state, delivery/audit data, and configured provider data. Exact scope is customer-specific. | `data-processing-overview.md`, V1 scope, provider inventory |
| Is Mantly a generic autonomous agent? | No. Production behavior is bounded by published runbooks, permissions, deterministic policies, approval settings, idempotency, and manual fallback. | `docs/v1-scope.md`, threat model, runbook tests |
| Which channels are production scope? | Email is the required V1 channel. Other repository channels are not automatically part of the active validation contract. | `docs/v1-scope.md` |
| Is the product production certified? | Do not claim certification unless a current independent certificate/report explicitly covers the service and scope. | Customer-specific evidence register |

## Hosting and architecture

| Question | Standard answer boundary | Evidence |
| --- | --- | --- |
| Where is data hosted? | Customer-specific hosted region or customer-managed infrastructure. All configured providers and support-access locations must be listed separately. | Completed `subprocessors.example.json`, deployment record |
| Is data multi-tenant? | Hosted SaaS can be multi-tenant with tenant/project/object authorization. The first pilot must include cross-tenant tests. | Threat model, CI tenant-isolation jobs |
| Is high availability provided? | The current standard single-node PocketBase/SQLite deployment does not provide HA or point-in-time recovery. Do not promise otherwise. | SaaS deployment guide, scaling boundaries |
| How are backups handled? | Daily encrypted off-host bundle of PocketBase and application state; 24-hour RPO, 4-hour RTO operating target, 30-day default retention, restore drills before pilot and quarterly. Customer contract may differ. | Backup runbook, CI restore drill, latest drill record |
| Can customers run on premises? | Commercially supported customer-managed deployment is available subject to license/distribution terms and the customer's operations responsibilities. | On-prem guide, licensing decision |

## Identity and access

| Question | Standard answer boundary | Evidence |
| --- | --- | --- |
| How are users authenticated? | PocketBase-backed authentication with application token exchange and forced password change for provisioned users in the current flow. Exact SSO/MFA capability must be answered from the deployed release, not roadmap intent. | Auth E2E workflow, deployment config |
| Is authorization server-side? | Yes, tenant/project/object and admin boundaries must be enforced at the backend; UI visibility is not considered authorization. | Threat model, tenant-isolation tests |
| How is privileged access controlled? | Customer-specific role assignment plus restricted infrastructure/PocketBase superuser access. Privileged operator access must have an approved purpose and audit evidence. | Access procedure, audit evidence |
| Is SSO/MFA supported? | Customer-specific/current-release answer only. Do not claim planned capability. | Release capability matrix |

## Application and AI security

| Question | Standard answer boundary | Evidence |
| --- | --- | --- |
| How is untrusted content handled? | Messages, HTML, attachments, retrieved documents, model output, and tool output are untrusted. Controls include sanitization, size/type limits, prompt/data separation, SSRF restrictions, provenance, policy validation, and human fallback. | Threat model, injection/phishing tests |
| Can a model execute arbitrary tools? | No. Tools are allowlisted, schema validated, permissioned per tenant/runbook, subject to deterministic policy and approval, and executed with idempotency/claim controls. | Threat model, action tests |
| How are hallucinations controlled? | Retrieval provenance, explicit uncertainty/no-match behavior, runbook/policy constraints, human review, review sampling, pause conditions, and outcome evaluation. No deterministic accuracy guarantee is claimed. | Pilot criteria, evaluation tests |
| Is customer data used to train general models? | Production baseline: not unless separately and validly approved. Actual provider API/enterprise data-use terms must be recorded per deployment. | Provider inventory and contract evidence |
| Are prompts/responses logged? | Content tracing is disabled by default. When approved, provider, region, retention, access, and deletion must be documented. Normal telemetry should be redacted. | Deployment config, observability policy |
| Can AI perform financial/destructive actions? | Human approval is required in the first pilot. Any later exception requires a reviewed action class, contract, test, and risk boundary. | V1 scope, threat model, runbook config |

## Secure development

| Question | Standard answer boundary | Evidence |
| --- | --- | --- |
| What checks run before merge? | Locked installs, Ruff, strict Pyright, full backend tests, branch coverage floor, frontend lint/build, real auth E2E, PocketBase/bootstrap/delivery integration, Docker builds, secret/dependency/config scans. | GitHub workflows, `docs/quality-contract.md` |
| Are dependencies monitored? | Weekly Dependabot plus pull-request/scheduled production dependency audits. Findings can be accepted only through a time-bounded reviewed risk process. | Dependabot config, security workflow, risk template |
| Is secret scanning enabled? | Repository history and pull-request scanning are configured. This does not replace deployment secret-store and rotation controls. | Security workflow |
| Is penetration testing performed? | Customer-specific and current evidence only. Do not claim a test that has not occurred. | Latest scoped report/remediation register |
| How are vulnerabilities reported? | Private reporting through GitHub private vulnerability reporting or the contracted security contact; response targets are documented. | `SECURITY.md` |

## Encryption and secrets

| Question | Standard answer boundary | Evidence |
| --- | --- | --- |
| Is transport encrypted? | Production endpoints require TLS at the deployment edge. Internal network protection depends on the deployment architecture and must be documented. | Deployment config/scan |
| Is data encrypted at rest? | Backup bundles are encrypted with `age` by default. Primary disk/volume encryption depends on the selected host/customer infrastructure and must not be assumed. | Backup runbook, infrastructure evidence |
| How are secrets stored? | Deployment secret store/environment, never source control. Secrets are unique per environment/tenant where applicable, redacted from logs, and rotated after suspected exposure. | Threat model, deployment procedure |
| Are backup keys separate? | Required. The age identity is not stored in the backup bundle or normal application data. | Backup runbook/drill |

## Privacy and data lifecycle

| Question | Standard answer boundary | Evidence |
| --- | --- | --- |
| What are the controller/processor roles? | Normally customer controller/responsible party and Mantly processor for hosted support processing, with narrow independent purposes. Must be confirmed contractually. | Processing overview, executed DPA |
| What subprocessors are used? | Deployment-specific; required and optional/customer-direct providers are distinguished. | Completed provider inventory |
| Are international transfers involved? | Provider- and account-specific. Locations, support access, transfer basis, and supplementary measures require current legal review. | Provider inventory and transfer assessment |
| What is retained and for how long? | Customer-configured periods by data class; proposed defaults are technical starting points, not automatic legal conclusions. | Retention policy and customer schedule |
| Can data be exported/deleted? | A controlled export/deletion process covers primary, derived, provider, cache/index, backup replay, and independent verification. It must be exercised before pilot. | Lifecycle procedure and exercise evidence |
| What happens on termination? | Access/connectors/automation stop, approved export is returned, credentials are revoked, active data is deleted after the agreed window, backups expire/replay deletion, and a minimized receipt records completion/exceptions. | Retention and lifecycle procedure |

## Incident response and continuity

| Question | Standard answer boundary | Evidence |
| --- | --- | --- |
| How are incidents handled? | Severity-based declaration, containment, evidence preservation, provider/customer coordination, staged recovery, and post-incident review. | Incident runbook and tabletop evidence |
| What is the notification time? | Contract/customer-specific. Internal severity response targets are not automatically a legal/contractual notification guarantee. | Executed agreement and incident contacts |
| Is disaster recovery tested? | A full synthetic Docker-volume backup/corrupt/restore test runs in CI; an operator drill with representative data is required before pilot and quarterly. | Workflow and latest drill record |
| Can automation be disabled? | Tenant, runbook, provider/connector, tool/action, and outbound paths require operational stop/manual fallback procedures. Exact controls must be demonstrated in the deployed release. | Incident runbook, operator test |

## Customer-specific completion record

| Field | Value |
| --- | --- |
| Customer/deployment | TBD |
| Release commit/image digest | TBD |
| Hosting/regions | TBD |
| Provider inventory version | TBD |
| Security review date | TBD |
| Latest restore drill | TBD |
| Latest incident tabletop | TBD |
| Latest dependency/config scan | TBD |
| Latest penetration test, if any | TBD/not performed |
| DPA/security schedule version | TBD |
| Retention/deletion schedule | TBD |
| Open high/critical risks | TBD/none |
| Approved by | TBD |

## Claim discipline

Before sending this evidence index:

- remove roadmap-only capabilities;
- replace generic answers with the actual deployment configuration;
- attach dates/versions and current evidence;
- disclose material limitations and open risks;
- have qualified legal/privacy owners review legal-role, transfer, and compliance answers;
- do not use “GDPR compliant,” “FADP compliant,” “zero retention,” “EU only,”
  “encrypted at rest,” “HA,” or “certified” unless the exact claim is supported
  across the entire configured service and contract.
