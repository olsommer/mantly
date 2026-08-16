# ADR 0002: Licensing and distribution model

- Status: **Accepted for this repository; release-specific legal review remains required**
- Date: 2026-07-26
- Owners: Product and engineering
- Reviewers required for external distribution: qualified legal counsel and the
  release owner

## Context

Mantly supports a hosted service and customer-operated Community deployments.
Customers need clear rights to inspect, run, modify, back up, restore, and
continue operating the software. Contributors and redistributors need one
unambiguous repository license.

The Community release already grants rights under GNU Affero General Public
License version 3. Those grants cannot be replaced retroactively by a
proprietary notice. A second, contradictory repository license would make the
boundary less clear and could not withdraw rights recipients already received.

This ADR records the current model. It is not customer-facing legal advice and
does not approve any particular release, hosted-service agreement, trademark
use, or third-party component.

## Decision

1. **This repository is AGPL-3.0-only.** Unless a file carries a valid,
   compatible third-party notice, Mantly Community source and documentation are
   offered under the `AGPL-3.0-only` terms in the root `LICENSE`.
2. **Existing grants stay in force.** A future edition, financing event, or
   business-model change does not revoke or narrow AGPL rights already granted.
   A future repository-wide license change would require authority from every
   relevant copyright holder and would not cancel earlier grants.
3. **Commercial use is allowed.** Mantly may charge for Cloud hosting,
   dedicated operation, onboarding, support, warranties, integrations, or other
   services. Those service terms do not replace the AGPL terms for Community
   code.
4. **Future closed components must be separate.** Independently developed
   commercial components may use separate terms when their architecture,
   copyright provenance, distribution, and interaction with AGPL code have been
   reviewed. They must not be described as changing the license of this
   repository.
5. **No alternative commercial source license exists today.** Dual licensing
   can be considered only when Mantly has the necessary copyright permissions,
   contributor provenance, product boundary, and counsel-approved terms.
6. **Customer-operated rights come from the AGPL.** Operators may run, inspect,
   modify, copy, back up, and continue using covered Community code subject to
   the license. Conveying object code requires the corresponding-source duties
   in section 6. Operators that modify the program and let users interact with
   it over a network must satisfy section 13. Support and uptime are separate
   contractual services; the AGPL itself promises neither.
7. **Community contributions use the same license.** Contributions are
   submitted under `AGPL-3.0-only` unless a file clearly states compatible
   third-party terms. No Contributor License Agreement or blanket relicensing
   grant is currently required. A contributor's separate, explicit permission
   would be needed for different licensing.
8. **Trademark rights remain separate.** The software license permits covered
   code uses, not misleading use of project names or marks. `TRADEMARKS.md`
   states the current trademark policy.
9. **Third-party terms remain controlling for third-party material.** Locked
   dependency inventories, reviewed notices, source obligations, and release
   SBOMs are part of the distribution gate.
10. **Legal review remains an external gate.** Qualified counsel must review
    customer-facing terms and release-specific third-party decisions before
    public distribution or commercial reliance. Repository automation cannot
    provide that approval.

## Options evaluated

| Model | SaaS defensibility | Enterprise/on-prem | Auditability and continuity | Contributions | Fork/competition risk | Dependency/trademark burden | Operational burden | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Proprietary source | Strong contractual control | Negotiated per customer | Only as contractually granted | Requires bespoke terms | Low public-fork risk | Full dependency review still required; trademarks separate | High contracting, access, escrow, and enforcement burden | Rejected for this repository; conflicts with existing AGPL grants |
| Source-available commercial license | Can restrict competing use | Can grant inspection and operation rights | Depends on bespoke terms | License-specific and often confusing | Medium | Not open source; compatibility review required | High license design and enforcement burden | Rejected now |
| Open core | Protects separate commercial modules | Flexible if boundary is real | Core remains inspectable | Good for core | Medium | Boundary and combined-work analysis required | High packaging and architecture burden | Possible future model only for independently developed components |
| AGPL plus alternative commercial license | Reciprocal network-source duty plus paid alternative | Can support negotiated alternatives | Strong Community continuity | Requires contributor relicensing permission | Medium | Dual-license provenance and compliance required | High rights-tracking burden | Not offered today; revisit only with complete permissions |
| Binaries/images without general source rights | Strong distribution control | Familiar procurement artifact | Weak without escrow/source rights | Minimal | Low | Cannot be used to avoid AGPL corresponding-source duties | Medium release/support burden | Rejected for covered Community code |
| Permissive open source | Weak reciprocal protection | Easy adoption | Strong source access | Low-friction | High | Simpler compatibility, trademarks still separate | Low license-administration burden | Rejected for current Community strategy |
| **AGPL-3.0-only Community repository** | Network modifications remain reciprocal | Self-hosting rights are explicit; services can still be sold | Source, modification, backup, and continuity rights are durable | Same-license contribution path | Forks allowed under reciprocal terms | Dependency, source, notice, and trademark controls still required | Moderate compliance burden | **Selected** |

## Repository and product boundaries

| Area | Current boundary |
| --- | --- |
| Community source, build scripts, and repository documentation | `AGPL-3.0-only`, unless a compatible third-party notice states otherwise |
| Mantly Cloud operation | Commercial service; Community code used by the service remains AGPL-covered |
| Support, onboarding, warranties, SLAs, and professional services | Separate commercial contracts |
| Future independently developed commercial components | Possible separate terms after architectural, provenance, and legal review |
| Customer data and configuration | Customer/contract rights, not relicensed by this repository |
| Names, logos, and domains | Trademark policy; no implied endorsement |
| Third-party packages and images | Their respective upstream terms |

## Distribution controls

Every external release must:

1. identify the exact source revision and object/container artifacts;
2. preserve `LICENSE`, `NOTICE.md`, `THIRD_PARTY_NOTICES.md`, copyright
   notices, and modification notices;
3. provide corresponding source in an AGPL-compliant manner for conveyed object
   code, including installation information when section 6 requires it;
4. expose the section 13 source offer to network users when applicable;
5. run the locked dependency license gate and create release/container SBOMs;
6. resolve new, missing, or unreviewed license metadata before release;
7. verify provenance and rights for icons, fonts, media, model weights, data,
   examples, and generated material;
8. keep trademark and service-contract wording separate from source rights; and
9. record release-owner and qualified-counsel approval outside repository
   automation.

## Consequences

The repository has a single clear license and Community users retain durable
self-hosting rights. Mantly can sell operation and support without pretending
that a service contract revokes source rights.

Costs remain: source-offer operations, section 13 behavior, contribution
provenance, third-party notices, release SBOMs, and reciprocal-license review.
Future closed or dual-licensed work requires a genuine separable boundary and
rights tracking.

## Revisit triggers

Create a new ADR if Mantly proposes a dual-license offer, independently
developed commercial component, acquisition of all necessary copyrights, a new
distribution channel, or a material change in Community contribution strategy.
Any new ADR must state that existing AGPL grants remain unaffected.
