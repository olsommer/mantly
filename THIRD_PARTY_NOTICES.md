# Third-party software notices

Mantly includes third-party software. Each project remains subject to its own
license; this file does not replace or modify those licenses.

This inventory covers the default Community build. Exact package versions and
transitive dependency metadata are recorded in `package-lock.json`, `uv.lock`,
and the CycloneDX SBOM artifacts produced by the dependency-license workflow.

## Browser applications

The Admin, Outlook add-in, and Landing applications include the following
direct runtime dependencies:

- MIT: DnD Kit, MDXEditor, PostHog React, Radix UI, Tailwind CSS and its Vite
  integration, TanStack Table, Axios, clsx, next-themes, PrismJS, React,
  React DOM, React Router, Recharts, Sonner, and tailwind-merge.
- Apache-2.0: class-variance-authority.
- Apache-2.0 AND MIT: posthog-js.
- ISC: Lucide and yaml.

Reviewed licenses in their locked transitive production graphs also include
0BSD, BSD-3-Clause, MIT AND ISC, MPL-2.0, Python-2.0, and
MPL-2.0 OR Apache-2.0. The legacy `format@0.2.2` package declares MIT through
its `licenses` metadata. The installed `posthog-js@1.406.2` distribution
declares Apache-2.0 AND MIT and includes both sets of notices in its `LICENSE`
file.

## Backend application

The default Python runtime includes these direct dependencies:

- MIT: FastAPI, LangChain, LangChain Google GenAI, LangChain OpenAI, PyJWT,
  PyYAML, SlowAPI, and Stripe.
- BSD-3-Clause: HTTPX, python-dotenv, Uvicorn, and websockets.
- Apache-2.0: just-bash and python-multipart.

Their locked transitive dependencies use permissive, Python Software
Foundation, CNRI, or MPL-2.0 terms. Refer to the backend CycloneDX SBOM for the
exact dependency-level inventory and bundled license texts.

The optional `attachments` dependency group, including Docling and its machine
learning stack, is not installed in the default Community images. It requires
a separate license and distribution review before release.

## Runtime and infrastructure

- PocketBase 0.36.5 is MIT licensed. Its complete license is shipped at
  `/usr/share/licenses/pocketbase/LICENSE` in the Mantly PocketBase image and
  is stored in `third_party/pocketbase/LICENSE` in this repository.
- Caddy is Apache-2.0 licensed.
- CPython is distributed under the Python Software Foundation License and
  other historical notices included by the upstream Python image.
- Node.js is MIT licensed and is used by the application build stages.
- Debian and Alpine base images contain operating-system packages under their
  respective licenses. Release-time container SBOM attestations provide the
  image-level package inventory.

Source links and full license texts remain available in each dependency's
source distribution. Redistributors must preserve all notices and satisfy the
corresponding license terms.
