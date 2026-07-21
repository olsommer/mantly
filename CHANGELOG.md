# Changelog

Notable Mantly changes will be recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and tagged releases
will follow semantic versioning once the public release process begins.

## [Unreleased]

## [0.1.0] - 2026-07-21

### Added

- AGPL-3.0 Community licensing and public contribution/security policies.
- Source-based Community Docker Compose deployment without license validation.
- Managed Cloud, Business, and Enterprise edition boundaries and usage
  entitlements.
- Canonical, idempotent agent-run metering across email and direct channels.
- Multi-concern runbook execution with one Inbox-owned response composer.
- Dependency-license policy checks, SBOM generation, secret scanning, and
  multi-architecture Community container releases.

### Fixed

- Fresh Community installs now create channel-webhook claim fields before the
  indexes that reference them.
- Browser dependency upgrades and overrides remove all currently reported npm
  advisories from the Admin, Outlook add-in, and Landing lockfiles.

### Security

- Hardened platform-admin authorization and SaaS startup invariants.
- Replaced recoverable stored license keys with SHA-256 digests and one-time
  plaintext delivery.
- Disabled automatic commercial license creation when secure delivery is not
  available.

[Unreleased]: https://github.com/olsommer/mantly/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/olsommer/mantly/releases/tag/v0.1.0
