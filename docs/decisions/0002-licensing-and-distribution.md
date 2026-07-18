# ADR 0002: Licensing and distribution model

- Status: **Accepted product direction; legal terms require qualified counsel approval**
- Date: 2026-07-16
- Owners: Product, commercial, engineering, and legal owners
- Supersedes: unresolved licensing language in the product vision

## Context

Mantly is a hosted and customer-managed agentic support product. Customers can
reasonably require deployment control, security review, continuity, backup,
auditability, and sometimes source escrow or limited inspection. At the same
time, publishing the complete platform under an open-source license before the
business model, contribution process, trademark policy, and commercial support
boundary are established would create irreversible rights and operational
obligations.

The repository was private and had no license file. Access to a private
repository does not create a clear customer, contractor, employee, contributor,
or evaluator rights model. The product vision also used phrases such as
self-hostable/source-available without a precise grant.

## Decision

For the current product stage:

1. **Mantly source code remains proprietary and private.**
2. **No copyright license is granted by repository access alone.** Rights arise
   only from an employment, contractor, contribution, evaluation, SaaS,
   on-premises, reseller, escrow, or other written agreement signed by the
   relevant legal entities.
3. **Hosted SaaS use is governed by written commercial terms**, including the
   service, data processing, security, support, acceptable-use, payment,
   suspension/termination, export/deletion, and liability boundaries.
4. **Customer-managed/on-premises distribution is governed by a written
   commercial license and support agreement.** It can grant the customer the
   rights needed to install, run, back up, restore, update, and operate the
   delivered release for the agreed entities, environments, users, and term.
5. **On-premises source access is not included by default.** Source review,
   escrow, modification, build rights, affiliate use, disaster-continuity rights,
   and post-termination operation are negotiated explicitly.
6. **The repository is not described as open source or source available.**
   “Self-hosted,” “on premises,” or “customer managed” describes the deployment
   model, not a public source-code license.
7. **External contributions are not accepted without written contribution terms.**
   Employment/contractor invention-assignment and confidentiality terms remain
   the primary contribution path at this stage.
8. **Third-party software obligations are inventoried and satisfied separately.**
   Mantly's proprietary notice does not replace upstream licenses, notices,
   source-offer obligations, or attribution.
9. **Mantly names, logos, domains, and product presentation remain separately
   protected.** A software license does not imply a trademark license.
10. **Qualified legal counsel must approve customer-facing license/terms before
    public distribution or commercial reliance.** The repository notice and this
    ADR prevent ambiguity; they are not a complete customer contract.

## Why this model now

- It preserves the ability to learn from the first design-partner pilot before
  creating irreversible public licensing expectations.
- It supports hosted SaaS and controlled on-premises delivery immediately through
  commercial agreements.
- It allows customer-specific audit, escrow, continuity, or source-review rights
  without granting them to every recipient.
- It avoids calling a non-open license “open source.”
- It keeps future options open: proprietary, source-available, open core, or dual
  licensing can still be evaluated after product-market, ecosystem, and legal
  evidence exists.

## Alternatives considered

### Public proprietary binaries/images only

**Advantages:** simple rights boundary and limited source exposure.

**Rejected as the entire strategy:** some enterprise/on-premises customers can
require source escrow, security review, continuity, or customer-specific
modification. Those can be negotiated without a public source grant.

### Source-available commercial license

**Advantages:** inspectability and community feedback while restricting hosted
competition or commercial use.

**Not selected now:** “source available” covers many incompatible grants. A
poorly chosen public license creates customer confusion, contribution
obligations, enforcement burden, and potentially conflicts with enterprise
terms. Revisit only with counsel and a precise commercial goal.

### Open core

**Advantages:** adoption/community around a useful core with proprietary
enterprise services.

**Not selected now:** the durable product boundary between core and commercial
features is not validated. Splitting prematurely risks an incoherent codebase and
misaligned incentives.

### AGPL plus commercial license

**Advantages:** recognized open-source license, reciprocal hosted-service
obligations, and a commercial alternative.

**Not selected now:** dual licensing requires clean copyright ownership,
contribution agreements, compliance operations, and a product/business decision
that the reciprocal model supports distribution. It would also grant broad
open-source rights immediately.

### Permissive open-source license

**Advantages:** low-friction adoption and contribution.

**Rejected for the current platform:** it would allow broad reuse, modification,
and competitive hosting with few reciprocal obligations before Mantly has a
validated ecosystem or monetization boundary.

## Customer-managed rights checklist

Every on-premises agreement must answer explicitly:

- licensed customer entities, affiliates, contractors, and environments;
- production, staging, development, disaster-recovery, and cold-standby copies;
- user/tenant/project/capacity limits and measurement;
- installation, backup, restore, monitoring, update, rollback, and migration rights;
- license-validation behavior and offline/grace operation;
- support, maintenance, security patch, and end-of-support windows;
- customer modification, integration, and configuration rights;
- source review or escrow trigger, scope, release, buildability, and confidentiality;
- continuity rights if Mantly ceases service, becomes insolvent, or materially
  breaches support obligations;
- data ownership, export, deletion, retention, and post-termination access;
- third-party components and separate upstream terms;
- audit and usage-verification methods that do not expose customer content;
- assignment, change of control, divestiture, and successor rights;
- termination, cure, suspension, and decommissioning procedure;
- warranty, indemnity, liability, insurance, and governing law;
- trademark and public-reference rights.

No license check may make customer data unrecoverable. Backup, export, and a safe
termination/continuity path remain part of the commercial design.

## Contribution model

Until a reviewed contributor agreement exists:

- only contributions covered by an applicable employment or contractor agreement
  and authorized repository access are accepted;
- no public pull-request invitation is made;
- contributors confirm they have the right to submit the work and disclose
  relevant third-party code/data/model assets;
- maintainers reject copied code, generated assets, or dependencies with unclear
  provenance;
- copyright ownership and any moral-rights/retained-rights treatment follow the
  applicable written agreement;
- a future open-source/dual-license decision requires a complete copyright and
  contribution provenance review.

## Third-party compliance

Before every distributed release:

1. generate the production dependency inventory;
2. identify license expression, copyright/notice, source, version, and whether the
   component is bundled, dynamically used, build-only, service-side, or separately
   installed;
3. review unknown, custom, copyleft, network-copyleft, source-available, font,
   model, media, and dataset terms;
4. include required notices/license texts and source offers;
5. verify commercial rights for logos, icons, screenshots, fonts, sample data,
   model weights, prompts, and documentation;
6. store the approved inventory and review evidence with the release artifact.

## Consequences

### Positive

- Current rights and terminology are unambiguous.
- SaaS and on-premises sales remain possible.
- Customer continuity/source-review needs can be negotiated proportionately.
- Future public licensing remains possible after evidence and counsel review.

### Costs and constraints

- Public community contributions and redistribution are not currently enabled.
- Customer procurement requires commercial terms and potentially escrow review.
- Mantly must maintain a third-party compliance process and release notices.
- Product/marketing must not imply rights that the agreement does not grant.

## Revisit triggers

Re-evaluate this ADR when one or more applies:

- repeated enterprise demand for source inspection/escrow follows a common pattern;
- an external contributor ecosystem becomes strategically valuable;
- a stable open-core boundary emerges from real customer use;
- partners require redistribution or embedded rights;
- a public marketplace/distribution channel imposes licensing requirements;
- acquisition/funding/strategic commitments change the business model;
- counsel recommends a source-available or dual-license model with clear benefits.

Any change requires a new ADR, copyright/provenance audit, third-party review,
trademark decision, contribution terms, migration/notice plan, and approved public
wording.
