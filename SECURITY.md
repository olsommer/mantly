# Security Policy

Mantly processes customer communications, attachments, operational knowledge,
and side-effecting support actions. Security reports are treated as confidential
until a coordinated disclosure decision is made.

## Supported versions

Mantly Community is currently a preview release. Security fixes target the
latest `0.1.x` release and the latest `main` revision. The deployed pilot release
must record its exact commit in deployment evidence and the pilot report.
Preview releases may contain breaking changes; upgrade to the latest patch
before reporting an issue.

Older commits, abandoned branches, demo deployments, and unsupported customer
forks receive best-effort support only. Commercial support contracts may define
different maintenance windows; those contractual terms take precedence for the
covered customer.

## Report a vulnerability

Do not open a public issue for a suspected vulnerability.

Report privately through one of these approved paths:

1. Email [support@mantly.io](mailto:support@mantly.io) with `SECURITY` in the
   subject.
2. GitHub private vulnerability reporting for this repository, when enabled.
3. The security contact identified in the applicable customer or pilot
   agreement.

Include, when possible:

- affected revision, release, deployment mode, endpoint, and component;
- reproduction steps, required privileges, or a minimal proof of concept;
- expected impact, including tenant or data-isolation impact;
- whether a side-effecting action can be triggered;
- evidence with customer content and secrets removed;
- suggested mitigation, workaround, or disclosure constraints;
- whether the issue is already being exploited.

Do not include customer data, live credentials, or production secrets. Use
synthetic examples and ask for a secure transfer method when sensitive material
is necessary. Do not access more data than necessary to demonstrate the issue or
test a customer environment without written authorization.

Mantly will confirm receipt, investigate, coordinate a fix, and discuss a
reasonable disclosure date. This public policy does not promise a contractual
response or remediation SLA.

## Response targets

These are internal operational targets, not contractual guarantees unless a
customer agreement says otherwise.

| Severity | Initial acknowledgement | Triage target | Mitigation target |
| --- | ---: | ---: | ---: |
| Critical | 4 hours | 8 hours | Immediate containment; fix or disable affected path as soon as safely possible |
| High | 1 business day | 2 business days | 7 calendar days |
| Medium | 3 business days | 5 business days | 30 calendar days |
| Low | 5 business days | 10 business days | Planned maintenance |

A critical issue includes suspected tenant-isolation failure, credential or
secret exposure, unauthorized destructive or financial action, remote code
execution, authentication bypass, or active exploitation.

## Scope

Reports may cover the Community source, Mantly Cloud, official container images,
and separately licensed commercial deployments. Vulnerabilities in third-party
services should normally be reported to their maintainers unless Mantly's
integration creates the exposure.

## Coordinated disclosure

- Reporter and maintainer should agree on a disclosure date after a fix or
  effective mitigation is available.
- Customer-impacting incidents follow `docs/security/incident-response.md`.
- Security advisories should describe affected versions, impact, remediation,
  and required customer actions without exposing private customer data.
- Credit is offered when requested and legally permitted.

## Security expectations for contributors

- Never commit credentials, customer messages, access tokens, private keys,
  production exports, or unredacted incident evidence.
- Treat email bodies, attachments, prompts, tool results, and traces as
  untrusted input.
- Enforce tenant and project authorization at the data-access boundary, not only
  in the UI.
- Require explicit permission, idempotency, and review rules for side-effecting
  tools.
- Preserve failure state and audit evidence; never hide or silently discard a
  customer-impacting failure.
- Add tests for authorization, replay, unsafe input, and failure behavior when a
  change touches a trust boundary.

## Security documentation

- Threat model: `docs/security/threat-model.md`
- Incident response: `docs/security/incident-response.md`
- Retention and deletion: `docs/security/data-retention.md`
- Backup and recovery: `docs/operations/backup-and-recovery.md` once merged
- DACH data-processing overview: `docs/compliance/data-processing-overview.md`
  once merged

## Good-faith research

Good-faith research that avoids privacy violations, destructive testing,
service disruption, and unauthorized data access is welcome. No bug-bounty or
formal safe-harbor program is currently offered. This policy does not override
customer contracts, third-party system rules, or applicable law.
