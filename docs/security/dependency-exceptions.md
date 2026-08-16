# Dependency audit exceptions

Production dependency audits fail on every high or critical advisory unless a
narrow exception is recorded in `npm-audit-exceptions.json`.

Each exception must name the exact advisory, affected package, permitted
application, expiry date, and technical justification. The audit gate rejects
expired, malformed, duplicate, package-mismatched, or application-mismatched
entries. Review owners must remove an exception when a safe compatible release
exists; expiry extension requires a fresh exploitability review.

## Active review: React Router RSC mode

`GHSA-QWWW-VCR4-C8H2` affects React Router's React Server Components mode before
an invalid request receives a `400` response. Mantly's `admin` and `addin`
packages are client-only Vite single-page applications. They use browser
routing and expose no React Server Components runtime, server actions, or React
Router framework action endpoint.

As of 2026-07-26, npm reports 7.18.1 as the newest release. Downgrading to the
suggested 7.11.0 restores multiple older high-severity open-redirect, XSS,
deserialization, and denial-of-service advisories. The exception therefore
expires on 2026-08-26 and covers only this advisory in these two applications.
