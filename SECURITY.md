# Security policy

Mantly processes customer communications, attachments, operational knowledge,
and side-effecting support actions. Security reports are treated as confidential
until a coordinated disclosure decision is made.

## Supported versions

| Version | Security support |
| --- | --- |
| Latest `main` and the currently deployed pilot release | Supported |
| Older commits, abandoned branches, demo deployments, and unsupported customer forks | Best effort only |

Until formal release versioning is introduced, the supported production commit
must be recorded in deployment evidence and the pilot report.

## Reporting a vulnerability

Do **not** open a public issue for a suspected vulnerability.

Report privately through one of these approved paths:

1. GitHub private vulnerability reporting for this repository, when enabled.
2. The security contact identified in the applicable customer or pilot agreement.
3. A private message to the repository owner if neither of the above is available.

Include, when possible:

- affected commit, deployment mode, endpoint, or component;
- reproduction steps and required privileges;
- tenant or data-isolation impact;
- whether a side-effecting action can be triggered;
- evidence with customer content and secrets removed;
- suggested mitigation or workaround;
- whether the issue is already being exploited.

Do not access more data than necessary to demonstrate the issue. Do not run tests
against a customer environment without written authorization.

## Response targets

These are operational targets, not contractual guarantees unless a customer
agreement says otherwise.

| Severity | Initial acknowledgement | Triage target | Mitigation target |
| --- | ---: | ---: | ---: |
| Critical | 4 hours | 8 hours | Immediate containment; fix or disable affected path as soon as safely possible |
| High | 1 business day | 2 business days | 7 calendar days |
| Medium | 3 business days | 5 business days | 30 calendar days |
| Low | 5 business days | 10 business days | Planned maintenance |

A critical issue includes suspected tenant isolation failure, credential or secret
exposure, unauthorized destructive/financial action, remote code execution,
authentication bypass, or active exploitation.

## Coordinated disclosure

- The reporter and maintainer should agree on a disclosure date after a fix or
  effective mitigation is available.
- Customer-impacting incidents follow `docs/security/incident-response.md`.
- Security advisories should describe affected versions, impact, remediation, and
  required customer actions without exposing private customer data.
- Credit is offered when requested and legally permitted.

## Security expectations for contributors

- Never commit credentials, customer messages, access tokens, private keys,
  production exports, or unredacted incident evidence.
- Treat email bodies, attachments, prompts, tool results, and traces as untrusted
  input.
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
- DACH data-processing overview: `docs/compliance/data-processing-overview.md` once merged

## Safe-harbor intent

Good-faith research that follows this policy, avoids privacy harm and service
disruption, and reports findings promptly will be treated as authorized to the
extent the repository owner is able to provide that assurance. This statement
does not override customer contracts, third-party system rules, or applicable
law.
