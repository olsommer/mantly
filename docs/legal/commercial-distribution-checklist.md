# Commercial distribution and licensing checklist

Status: **Release and deal gate; qualified legal approval required**

This checklist turns the licensing decision into an executable commercial handoff.
It does not create customer rights by itself. The signed agreement and approved
release schedule are authoritative.

## 1. Product and delivery model

- [ ] Delivery is classified as hosted SaaS, customer-managed/on-premises,
  evaluation, proof of concept, reseller/embedded, source review, or escrow.
- [ ] Licensed legal entities, affiliates, contractors, environments, and regions
  are identified.
- [ ] Production, staging, development, disaster-recovery, test, and cold-standby
  copies are explicitly allowed or excluded.
- [ ] User, tenant, project, volume, model/provider, and capacity limits are clear
  and measurable without inspecting customer content.
- [ ] The release commit, image digests, package checksum, and supported deployment
  topology are recorded.
- [ ] “Self-hosted” or “on premises” is not described as open source or source
  available.

## 2. Rights granted

For customer-managed delivery, state whether the customer may:

- [ ] install and run the delivered release;
- [ ] make operational backup, restore, standby, and migration copies;
- [ ] reproduce the package internally for approved environments;
- [ ] configure, integrate, and write customer-owned adapters;
- [ ] modify source, scripts, or configuration;
- [ ] engage approved contractors and managed-service providers;
- [ ] inspect source for security/compliance review;
- [ ] receive source escrow and use it after a defined release trigger;
- [ ] continue operating after subscription/support termination;
- [ ] transfer rights during merger, divestiture, outsourcing, or change of control;
- [ ] use documentation, APIs, and exported data after termination.

Every right must define scope, term, confidentiality, support consequence, and
whether derivative works can be distributed or used outside the licensed group.

## 3. Restrictions

- [ ] No public redistribution, resale, sublicensing, hosted service, or competitive
  use is assumed unless expressly granted.
- [ ] Reverse engineering restrictions preserve non-waivable legal rights and
  agreed interoperability/security review rights.
- [ ] Benchmark/publication restrictions are proportionate and do not prevent
  mandatory regulatory disclosure.
- [ ] Customer data and customer-developed integrations remain treated according
  to the signed agreement.
- [ ] Trademark, endorsement, public-reference, and reseller rights are separate.
- [ ] License enforcement cannot silently delete, corrupt, encrypt, or make
  customer data unrecoverable.

## 4. License validation and continuity

- [ ] Online/offline validation behavior is documented.
- [ ] Grace period, clock/network failure, license-server outage, and administrative
  recovery are defined.
- [ ] Suspension/termination disables only the agreed product access; export,
  backup, restoration, and legally required access remain safe.
- [ ] Customer can recover data without a functioning Mantly license server.
- [ ] Disaster-recovery and cold-standby instances can be activated under defined
  conditions.
- [ ] Escrow trigger, deposit contents, update cadence, build verification,
  beneficiary rights, and release procedure are defined when purchased.
- [ ] Business discontinuation, insolvency, acquisition, and end-of-life rights are
  addressed.

## 5. Support and maintenance

- [ ] Supported versions and environments are listed.
- [ ] Security and critical-fix obligations, customer deployment deadline, and
  unsupported modification boundary are clear.
- [ ] Support access, diagnostics, telemetry, and customer-content handling are
  contractually controlled.
- [ ] Availability, response, recovery, and maintenance commitments match the
  actual architecture.
- [ ] Upgrade, migration, rollback, and end-of-support processes are defined.
- [ ] Customer can retain the last licensed release and documentation as agreed.

## 6. Security, privacy, and AI

- [ ] DPA, security schedule, provider inventory, data locations, retention,
  deletion, export, incident, and audit terms are complete.
- [ ] Approved model providers/models, training/data-use setting, region, and
  customer BYOK/local options are recorded.
- [ ] Human-review and prohibited-action boundaries match the deployed runbooks.
- [ ] Customer-facing AI disclosure, contest, correction, and escalation duties are
  allocated.
- [ ] Product claims link to current technical evidence and disclose limitations.
- [ ] No certification, residency, encryption, retention, accuracy, or HA claim is
  made without exact evidence.

## 7. Third-party software and assets

- [ ] `third-party-inventory.json` was generated from the locked release.
- [ ] Every review-category component has an approved decision or replacement.
- [ ] Full required license texts, copyright notices, NOTICE files, attributions,
  source offers, relinking/build materials, and modification notices are included.
- [ ] Base images, OS packages, bundled browser code, fonts, icons, screenshots,
  models, tokenizers, datasets, prompts, and demo assets are reviewed.
- [ ] Customer-specific plugins/assets have documented ownership and distribution
  rights.
- [ ] No customer data or confidential evidence is packaged.

## 8. Package contents

A customer-managed release should contain or reference:

```text
LICENSE.md
NOTICE.md
THIRD_PARTY_NOTICES.md
third-party-inventory.json
release-manifest.json
docker-compose.yml
.env.example
support and recovery scripts
operations, security, privacy, and deployment documentation
image names and immutable digests
checksums/signature or provenance evidence
```

- [ ] Package checksum and optional signature/provenance are verified.
- [ ] Images are pinned to approved immutable digests rather than an unreviewed
  `latest` tag for final delivery.
- [ ] Recovery, export, and termination procedures are included.
- [ ] Customer package references the signed agreement rather than pretending
  `LICENSE.md` is the complete commercial license.

## 9. Commercial and legal terms

- [ ] Fees, taxes, usage measurement, invoice, renewal, and price-change process are
  clear.
- [ ] Evaluation/pilot rights automatically expire or convert only as agreed.
- [ ] Warranty, disclaimers, indemnities, liability caps/exclusions, insurance,
  governing law, venue, and order of precedence are reviewed.
- [ ] IP ownership for Mantly, customer data, customer configurations, feedback,
  integrations, and jointly developed work is explicit.
- [ ] Confidentiality, trade-secret handling, residuals, and compelled disclosure
  are addressed.
- [ ] Assignment, subcontracting, change of control, audit, export control,
  sanctions, acceptable use, and regulatory cooperation are addressed where
  applicable.
- [ ] Termination, cure, suspension, export, deletion, transition assistance, and
  survival are complete.

## 10. Approval record

| Review | Owner | Evidence/version | Decision | Open items |
| --- | --- | --- | --- | --- |
| Product/delivery scope | TBD | TBD | approve/reject | TBD |
| Engineering/release | TBD | TBD | approve/reject | TBD |
| Security/privacy | TBD | TBD | approve/reject | TBD |
| Third-party/provenance | TBD | TBD | approve/reject | TBD |
| Commercial/finance | TBD | TBD | approve/reject | TBD |
| Qualified legal counsel | TBD | TBD | approve/reject | TBD |
| Customer authorized signer | TBD | executed agreement | approve/reject | TBD |

## Release decision

- [ ] Approved for hosted SaaS deployment under executed terms.
- [ ] Approved for customer-managed delivery under executed license/support terms.
- [ ] Approved only for time-bounded evaluation/pilot.
- [ ] Blocked pending listed remediation or legal approval.

Repository completion does not mark this checklist approved. Each commercial
release/customer arrangement needs its own completed record.