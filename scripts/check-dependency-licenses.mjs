#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const applications = ["admin", "addin", "landing"];

// Keep this list narrow and reviewed. A new expression must be inspected before
// it is accepted, even when it represents an OSI-approved license.
const allowedLicenseExpressions = new Set([
  "0BSD",
  "Apache-2.0",
  "(Apache-2.0 AND MIT)",
  "BSD-3-Clause",
  "ISC",
  "MIT",
  "MIT AND ISC",
  "MPL-2.0",
  "(MPL-2.0 OR Apache-2.0)",
  "Python-2.0",
]);

// Old package metadata that has been checked against the installed license.
// Pin the version so an update requires a fresh review.
const reviewedLicenseOverrides = new Map([
  ["format@0.2.2", "MIT"],
]);

const prohibitedPackages = new Set([
  "@codesandbox/nodebox",
  "@codesandbox/sandpack-client",
  "@codesandbox/sandpack-react",
]);

function packageName(lockPath) {
  const marker = "node_modules/";
  return lockPath.slice(lockPath.lastIndexOf(marker) + marker.length);
}

const failures = [];
let checkedPackages = 0;

for (const application of applications) {
  const lockPath = join(root, application, "package-lock.json");
  const lock = JSON.parse(readFileSync(lockPath, "utf8"));

  for (const [dependencyPath, metadata] of Object.entries(lock.packages ?? {})) {
    if (!dependencyPath.startsWith("node_modules/")) continue;
    const name = packageName(dependencyPath);
    const version = metadata.version ?? "unknown";
    const key = `${name}@${version}`;

    if (prohibitedPackages.has(name)) {
      failures.push(`${application}: prohibited package ${key}`);
      continue;
    }

    if (metadata.dev) continue;

    checkedPackages += 1;
    const license = reviewedLicenseOverrides.get(key) ?? metadata.license;

    if (!license) {
      failures.push(`${application}: missing license metadata for ${key}`);
      continue;
    }

    if (!allowedLicenseExpressions.has(license)) {
      failures.push(`${application}: unreviewed license ${license} for ${key}`);
    }
  }
}

for (const dockerfile of ["Dockerfile", "Dockerfile.api", "Dockerfile.onprem"]) {
  const contents = readFileSync(join(root, dockerfile), "utf8");
  if (/uv sync[^\n]*(?:--all-extras|--extra\s+attachments)/.test(contents)) {
    failures.push(`${dockerfile}: optional attachments dependencies must not ship by default`);
  }
}

if (failures.length > 0) {
  console.error("Dependency license policy failed:\n");
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log(
  `Dependency license policy passed: ${checkedPackages} production npm package entries checked; ` +
    "CodeSandbox runtime absent; optional attachments runtime absent.",
);
