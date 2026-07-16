# Third-party license and provenance process

Status: **Required release control; legal review required for review-category items**

Owner: Release owner with engineering and legal/procurement reviewers

## 1. Scope

Review everything included in, linked into, downloaded by, or required to operate
a distributed Mantly release:

- Python runtime and transitive dependencies;
- admin, add-in, and landing production dependencies bundled into JavaScript/CSS;
- PocketBase, Caddy, base/container images, OS packages, and build tools whose
  notices must accompany the image or package;
- fonts, icons, images, screenshots, audio/video, sample data, templates, and
  documentation excerpts;
- model weights, tokenizers, embeddings, prompts, datasets, evaluation cases, and
  generated assets;
- Microsoft/store manifests, SDKs, provider clients, and integration examples;
- code copied or adapted from issues, snippets, examples, previous products, or
  generated-code systems;
- customer-specific plugins/configurations delivered with the product.

SaaS-only server use can create different obligations from customer distribution,
but it is not exempt from license, service-term, model/data, attribution, or
network-copyleft review.

## 2. Release inventory

Run from the locked release environment:

```bash
cd backend
uv sync --frozen
uv run python ../scripts/generate_third_party_notice.py \
  --root .. \
  --json-out ../dist/third-party-inventory.json \
  --markdown-out ../dist/THIRD_PARTY_NOTICES.md
```

The tool inventories:

- the production Python dependency graph exported by `uv` and resolved against
  installed distribution metadata;
- non-dev package-lock entries for admin, add-in, and landing applications;
- package name, version, ecosystem, source/reference, declared license, and
  review category.

The generated inventory is evidence input, not automatic legal approval. Package
metadata can be incomplete or inaccurate; custom licenses and bundled assets
require source inspection.

## 3. Classification

### Usually notice/attribution review

Examples include commonly used permissive licenses such as MIT, ISC, BSD,
Apache-2.0, 0BSD, and similar terms. Review still verifies:

- correct component/version;
- required license/copyright/NOTICE text;
- Apache modification/patent/NOTICE obligations;
- attribution presentation;
- asset/font/model terms separate from code;
- no additional repository-specific restrictions.

### Mandatory legal review

- unknown, missing, custom, or ambiguous license;
- GPL, AGPL, LGPL, SSPL, EUPL, EPL, CDDL, MPL, OSL, or another reciprocal/
  network/source-disclosure term;
- source-available or field-of-use restriction;
- non-commercial, research-only, evaluation-only, responsible-AI/use-policy, or
  no-redistribution term;
- font, icon, media, data, model, tokenizer, prompt, or dataset license;
- dual/multi-license choice;
- dependency with required source offer, relinking, modification disclosure, or
  installation-information obligations;
- package metadata conflicting with upstream repository terms;
- component copied or vendored without package metadata;
- provider SDK/service terms restricting benchmarking, caching, reverse
  engineering, output use, or resale.

No review-category item is shipped merely because a CI scan found no known CVE.

## 4. Required evidence per component

- canonical component/project and package name;
- exact version, commit, image digest, or asset hash;
- source URL/reference and supplier;
- where/how used: server-only, bundled frontend, image, customer package,
  dynamically linked, separate service, build-only, optional plugin;
- license expression and full text source;
- copyright/NOTICE/attribution;
- modifications or vendored patches;
- required source offer/relinking/build material;
- reviewer and decision;
- release(s) covered and expiry/re-review trigger.

Do not put private registry credentials or customer data in the inventory.

## 5. Container and customer package

Before packaging:

- identify base images and their OS/package notices;
- pin immutable image digest for the approved release;
- copy Mantly `LICENSE.md`, `NOTICE.md`, and approved generated third-party
  notices into the package;
- include upstream license texts/NOTICE/source offers required for redistributed
  components;
- record package checksum and generated-at release commit;
- verify that customer scripts do not download an unreviewed `latest` dependency;
- verify Microsoft/store/browser/client-side bundles separately from backend
  server dependencies.

## 6. Models, data, fonts, and generated material

Code-package scanners do not answer whether Mantly may commercially use or
redistribute:

- model weights/tokenizers or local inference runtime;
- provider-generated output used as product content;
- public benchmark/evaluation datasets;
- screenshots, email samples, company logos, icons, fonts, photos, and demo data;
- generated code whose prompt/source included restricted code or customer data.

Maintain a provenance record with source, author/tool, date, inputs classification,
license/terms, commercial-use/distribution decision, and reviewer.

## 7. Change triggers

Re-run inventory and review when:

- a dependency or lockfile changes;
- build/container base or OS packages change;
- a new provider, model, dataset, font, icon, or asset is added;
- a component moves from server-only to customer distribution or bundled client;
- an upstream project changes license or ownership;
- Mantly changes public/proprietary/source-distribution model;
- a customer agreement requires a software bill of materials, source offer, or
  additional attribution.

## 8. Release gate

A distributed release is blocked when:

- generated inventory is missing or does not match lockfiles/images;
- a mandatory-review component lacks a written decision;
- required notice/license/source offer is absent;
- component provenance is unknown;
- a license is incompatible with the intended proprietary/SaaS/on-prem use;
- a copied/customer/generated asset lacks commercial rights;
- the customer package omits Mantly and third-party notices;
- marketing describes third-party compatibility as endorsement.

Exceptions require a time-bounded written legal/release decision. A security risk
acceptance cannot waive copyright/license obligations.
