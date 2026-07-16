# Contributing to Mantly

Mantly is currently developed in a private proprietary repository. This file
does not invite public contributions or grant a source-code license.

## Who may contribute

A contribution is accepted only when the contributor:

- has authorized repository access;
- is covered by an applicable employment, contractor, or separately signed
  contribution agreement that grants the required rights;
- has authority from their organization to submit the work;
- can identify any third-party code, model output, assets, data, fonts, media,
  prompts, or documentation included in the change;
- follows the security, privacy, quality, and release requirements in this
  repository.

Do not submit code copied from another project, generated from confidential or
restricted sources, or licensed under terms incompatible with Mantly's intended
commercial distribution.

## Contribution statement

By submitting work, the contributor confirms—subject to their applicable written
agreement—that:

1. they created the contribution or have the right to submit it;
2. they disclosed third-party and generated material plus its provenance/terms;
3. the contribution does not intentionally contain credentials, personal data,
   customer content, malware, or another party's confidential information;
4. the contribution can be used, modified, distributed, hosted, sublicensed, and
   commercially licensed by the applicable Mantly rights holder as stated in the
   governing agreement;
5. no additional terms are introduced through comments, snippets, assets,
   dependencies, or generated files without explicit maintainer approval.

If the contributor cannot make these confirmations, do not submit the change;
contact the repository owner privately.

## Development requirements

- Link work to an approved issue, scope decision, or pilot evidence.
- Preserve tenant isolation, permissions, idempotency, audit, recovery, and safe
  manual fallback.
- Add tests for behavior and failure paths.
- Run the complete local quality contract.
- Update security/privacy/operations/provider/license evidence when the data,
  tool, provider, distribution, or runtime boundary changes.
- Never commit secrets, customer data, production exports, model weights, or
  unapproved binary assets.
- Use synthetic fixtures and redacted evidence.
- Keep commits and PRs explicit about generated code/assets and third-party
  sources.

## Review and acceptance

Maintainers may reject or require replacement of a contribution when rights,
provenance, security, quality, or product scope are unclear. Acceptance of a pull
request does not override the contributor's governing agreement or create public
rights in the repository.

## Future public contribution model

A public/open-source, source-available, open-core, or dual-license contribution
process requires a new licensing decision, contributor terms, copyright and
provenance audit, trademark policy, and public documentation. Until then, no
public Contributor License Agreement or Developer Certificate of Origin is
asserted.
