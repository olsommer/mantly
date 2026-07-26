# Security Policy

## Supported versions

Mantly Community is currently a preview release. Security fixes target the
latest `0.1.x` release and the latest `main` revision. Preview releases may
contain breaking changes; upgrade to the latest patch before reporting an
issue.

Commercial support contracts may define different maintenance windows. Those
contractual terms take precedence for the covered customer.

## Report a vulnerability

Do not open a public issue for a suspected vulnerability. Email
[support@mantly.io](mailto:support@mantly.io) with `SECURITY` in the subject.

Include, when possible:

- Affected revision, release, deployment mode, and component.
- Reproduction steps or a minimal proof of concept.
- Expected impact and any known prerequisites.
- Suggested remediation or disclosure constraints.

Do not include customer data, live credentials, or production secrets. Use
synthetic examples and ask for a secure transfer method when sensitive material
is necessary.

Mantly will confirm receipt, investigate, coordinate a fix, and discuss a
reasonable disclosure date. This public policy does not promise a response or
remediation SLA.

## Scope

Reports may cover the Community source, Mantly Cloud, official container images,
and separately licensed commercial deployments. Vulnerabilities in third-party
services should normally be reported to their maintainers unless Mantly's
integration creates the exposure.

Good-faith research that avoids privacy violations, destructive testing,
service disruption, and unauthorized data access is welcome. No bug-bounty or
safe-harbor program is currently offered.
