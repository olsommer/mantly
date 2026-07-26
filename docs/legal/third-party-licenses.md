# Third-party license inventory and release gate

## Purpose

Mantly Community is `AGPL-3.0-only`, but dependencies and bundled artifacts keep
their upstream terms. This process makes the default locked application
inventory reproducible and makes dependency changes fail closed until their
metadata is accounted for.

Automation is evidence, not legal approval. Package metadata can be incomplete
or wrong. Release owners must still review obligations, ship required texts and
source, and obtain qualified legal advice where needed.

## Canonical inputs

- `backend/uv.lock` plus the default (no extras, no dev group) Python
  environment installed with `uv sync --frozen --no-dev`;
- `admin/package-lock.json`, `addin/package-lock.json`, and
  `landing/package-lock.json`, excluding entries marked development-only;
- `docs/legal/dependency-license-policy.json`, containing the narrow accepted
  SPDX-expression set and version-pinned metadata overrides;
- `third_party/pocketbase/LICENSE` and the pinned PocketBase version in
  `pocketbase/Dockerfile`.

The generator never edits source, lock, policy, or workflow files. It sorts all
records and omits timestamps, producing byte-stable JSON/Markdown for identical
inputs and installed locked artifacts.

## Commands

Install the exact default backend environment:

```sh
uv sync --directory backend --frozen --no-dev
```

Validate npm policy:

```sh
node scripts/check-dependency-licenses.mjs
```

Generate exact evidence:

```sh
mkdir -p artifacts/licenses
(
  cd backend
  uv run --frozen --no-dev python ../scripts/generate_third_party_notice.py \
    --root .. \
    --check \
    --json-out ../artifacts/licenses/third-party-inventory.json \
    --markdown-out ../artifacts/licenses/THIRD_PARTY_INVENTORY.md
)
```

Without output arguments the generator prints JSON to stdout and does not write
files.

## Policy behavior

- SPDX expressions are matched exactly. Substring matches such as treating an
  unknown expression containing `MIT` as approved are forbidden.
- A missing expression fails unless a package/version-specific override records
  reviewed evidence.
- Overrides are pinned to package and version. Updating that package makes the
  gate fail until its metadata is inspected again.
- The accepted-expression set is an engineering review boundary, not a claim
  that every use is legally compatible.
- Optional Python extras are excluded from the default Community inventory and
  require their own inventory before distribution.
- New lockfiles, package ecosystems, bundled binaries, fonts, images, models, or
  datasets must be added to this process before release.

## Release evidence not covered by lockfiles

The dependency workflow produces Python and npm CycloneDX SBOMs. Container
builds produce image SBOM/provenance attestations covering base images,
operating-system packages, Node, CPython, Caddy, and other layer contents.
Release review must retain those artifacts and reconcile their license findings.

The checked-in `THIRD_PARTY_NOTICES.md` is the reviewed human summary. Generated
inventory is exact machine evidence; neither file replaces full upstream
license texts or corresponding-source duties.

## Handling a failure

1. Identify the exact package, version, artifact, and usage.
2. Inspect the upstream source distribution and complete license text.
3. Confirm provenance and required notices/source obligations.
4. Replace the component or update the narrow policy with a version-pinned,
   evidence-based decision.
5. Regenerate inventory/SBOMs and attach the review decision to the release.
6. Escalate custom, unknown, reciprocal, source-available, non-commercial,
   font, media, model, dataset, or conflicting terms to qualified counsel.
