#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const applications = ["admin", "addin", "landing"];
const policyPath = join(root, "docs", "legal", "dependency-license-policy.json");
const policy = JSON.parse(readFileSync(policyPath, "utf8"));

if (policy.schemaVersion !== "1.0") {
  throw new Error(`${policyPath}: unsupported schemaVersion`);
}
if (!Array.isArray(policy.acceptedSpdxExpressions)) {
  throw new Error(`${policyPath}: acceptedSpdxExpressions must be an array`);
}

// One shared policy feeds the npm gate and the deterministic all-ecosystem
// inventory. Expressions are exact values; no substring inference is allowed.
const allowedLicenseExpressions = new Set(policy.acceptedSpdxExpressions);
const reviewedLicenseOverrides = new Map(
  Object.entries(policy.nodeOverrides ?? {}).map(([key, record]) => {
    if (!record || typeof record.spdx !== "string" || typeof record.evidence !== "string") {
      throw new Error(`${policyPath}: invalid node override ${key}`);
    }
    return [key, record.spdx];
  }),
);
const prohibitedPackages = new Set(policy.prohibitedNodePackages ?? []);

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
