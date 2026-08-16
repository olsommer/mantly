# AGPL Community release and commercial-services checklist

Use this checklist for an external Community release, customer-operated
delivery, or a commercial service built with this repository. It records
engineering and release evidence. It does not replace qualified legal review.

## 1. Release identity

- [ ] Record source commit/tag, build workflow run, artifact digests, image
  digests, release owner, intended recipients, and distribution date.
- [ ] Confirm every delivered binary/image can be mapped to its exact
  corresponding source.
- [ ] Record whether the release is source-only, object/container distribution,
  hosted network use, or a combination.

## 2. Repository license

- [ ] Include the root `LICENSE` (`AGPL-3.0-only`), `NOTICE.md`,
  `THIRD_PARTY_NOTICES.md`, and `TRADEMARKS.md`.
- [ ] Preserve copyright, license, warranty, attribution, and modification
  notices.
- [ ] Do not add customer terms that prohibit exercise of AGPL rights in the
  covered Community code.
- [ ] Do not describe Community rights as revocable, term-limited, license-key
  dependent, or available only under a commercial agreement.

## 3. Corresponding source and network use

- [ ] For conveyed object code, select and document an allowed AGPL section 6
  source-delivery method.
- [ ] Confirm corresponding source includes build, install, and control scripts
  plus required interface definitions.
- [ ] Include installation information when section 6 requires it.
- [ ] Keep the source offer available for the required period and to the
  required recipients.
- [ ] For modified network deployments, make the section 13 source offer
  prominent and usable by interacting users.
- [ ] Test the source path from a clean environment; do not rely on private
  employee-only access.

## 4. Third-party and artifact evidence

- [ ] Run `node scripts/check-dependency-licenses.mjs`.
- [ ] Generate the deterministic locked inventory with
  `scripts/generate_third_party_notice.py --check`.
- [ ] Resolve every missing/untracked expression or pinned override change.
- [ ] Generate Python, npm, and release-container SBOMs.
- [ ] Include required upstream license texts, attributions, source offers, and
  modification notices.
- [ ] Review optional dependency groups separately before shipping them.
- [ ] Review icons, fonts, media, sample data, generated content, model weights,
  prompts, and documentation provenance.
- [ ] Store inventory, SBOMs, notices, and review decisions with the release.

Passing automation means known locked metadata matched repository policy. It
does not prove compatibility, satisfy every notice obligation, or constitute
legal approval.

## 5. Commercial service boundary

- [ ] Service, support, warranty, SLA, privacy, security, and payment terms are
  clearly separate from the Community source license.
- [ ] Suspension or contract termination does not claim to revoke copies or
  rights already received under the AGPL.
- [ ] Customers can export their data and recover it without a commercial
  license-server dependency.
- [ ] Any separately licensed component is independently identified, packaged,
  and reviewed; Community notices do not claim it is part of this repository.
- [ ] Marketing uses “open source,” “AGPL,” “self-hosted,” “customer-operated,”
  “Cloud,” and “commercial service” precisely.

## 6. On-premises operations

- [ ] Deployment instructions identify Community source and AGPL obligations.
- [ ] Backup, restore, update, rollback, migration, and data-export procedures
  do not depend on revocable source access.
- [ ] Contractual support/end-of-support terms do not purport to end Community
  run or modification rights.
- [ ] Customer-specific credentials, data, or confidential configuration are
  excluded from general artifacts.

## 7. Approval record

- [ ] Engineering release owner approved artifact/source traceability.
- [ ] Security/privacy owners approved their applicable evidence.
- [ ] Qualified legal counsel reviewed the release-specific license,
  corresponding-source, third-party, trademark, and customer-term boundary.
- [ ] Open exceptions list an owner, deadline, affected artifact, and explicit
  stop-ship decision.

Issue #11 remains open until the required legal review and release-specific
third-party decisions are complete.
