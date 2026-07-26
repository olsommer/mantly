import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { basename, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const target = process.argv[2];
if (!target) {
  console.error("Usage: node scripts/check-node-audit.mjs <package-directory>");
  process.exit(2);
}

const cwd = resolve(target);
const application = basename(cwd);
const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const exceptionPath = resolve(
  repositoryRoot,
  "docs/security/npm-audit-exceptions.json",
);
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const result = spawnSync(
  npmCommand,
  ["audit", "--omit=dev", "--audit-level=high", "--json"],
  {
    cwd,
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
    shell: process.platform === "win32",
  },
);

if (result.error) {
  console.error(`Unable to run npm audit in ${cwd}: ${result.error.message}`);
  process.exit(1);
}

let report;
try {
  report = JSON.parse(result.stdout);
} catch {
  if (result.stderr) {
    process.stderr.write(result.stderr);
  }
  console.error(`npm audit returned invalid JSON in ${cwd}.`);
  process.exit(1);
}

if (report.error) {
  console.error(`npm audit failed in ${cwd}: ${report.error.summary ?? "unknown error"}`);
  process.exit(1);
}

const counts = report.metadata?.vulnerabilities;
if (!counts) {
  console.error(`npm audit omitted vulnerability totals in ${cwd}.`);
  process.exit(1);
}

let exceptionDocument;
try {
  exceptionDocument = JSON.parse(readFileSync(exceptionPath, "utf8"));
} catch (error) {
  console.error(`Unable to read ${exceptionPath}: ${error.message}`);
  process.exit(1);
}

if (
  exceptionDocument.schemaVersion !== 1 ||
  !Array.isArray(exceptionDocument.exceptions)
) {
  console.error(`Invalid npm audit exception schema in ${exceptionPath}.`);
  process.exit(1);
}

const today = new Date().toISOString().slice(0, 10);
const exceptions = new Map();
for (const exception of exceptionDocument.exceptions) {
  if (
    typeof exception.advisory !== "string" ||
    !Array.isArray(exception.packages) ||
    !Array.isArray(exception.applications) ||
    typeof exception.expiresOn !== "string" ||
    typeof exception.justification !== "string" ||
    exception.justification.trim().length < 20
  ) {
    console.error(`Malformed npm audit exception: ${JSON.stringify(exception)}`);
    process.exit(1);
  }
  if (exceptions.has(exception.advisory)) {
    console.error(`Duplicate npm audit exception: ${exception.advisory}`);
    process.exit(1);
  }
  exceptions.set(exception.advisory, exception);
}

function advisoryId(advisory) {
  const ghsa = advisory.url?.match(/GHSA-[0-9a-z-]+/i)?.[0];
  return ghsa?.toUpperCase() ?? `NPM-${advisory.source}`;
}

function directAdvisories(packageName, visited = new Set()) {
  if (visited.has(packageName)) {
    return [];
  }
  visited.add(packageName);

  const vulnerability = report.vulnerabilities?.[packageName];
  if (!vulnerability || !Array.isArray(vulnerability.via)) {
    return [];
  }

  const advisories = [];
  for (const via of vulnerability.via) {
    if (typeof via === "string") {
      advisories.push(...directAdvisories(via, new Set(visited)));
    } else if (via?.severity === "high" || via?.severity === "critical") {
      advisories.push(via);
    }
  }
  return advisories;
}

const unresolved = [];
const accepted = new Set();
for (const [packageName, vulnerability] of Object.entries(
  report.vulnerabilities ?? {},
)) {
  if (
    vulnerability.severity !== "high" &&
    vulnerability.severity !== "critical"
  ) {
    continue;
  }

  const advisories = directAdvisories(packageName);
  if (advisories.length === 0) {
    unresolved.push(`${packageName}: audit returned no attributable advisory`);
    continue;
  }

  for (const advisory of advisories) {
    const id = advisoryId(advisory);
    const exception = exceptions.get(id);
    const dependency = advisory.dependency ?? advisory.name ?? packageName;
    if (
      exception &&
      exception.packages.includes(dependency) &&
      exception.applications.includes(application) &&
      exception.expiresOn >= today
    ) {
      accepted.add(`${id} (${dependency})`);
      continue;
    }
    const expiry =
      exception && exception.expiresOn < today
        ? `; exception expired ${exception.expiresOn}`
        : "";
    unresolved.push(`${id} (${dependency}, ${advisory.severity})${expiry}`);
  }
}

const high = Number(counts.high ?? 0);
const critical = Number(counts.critical ?? 0);
console.log(
  `Production vulnerabilities: low=${Number(counts.low ?? 0)}, ` +
    `moderate=${Number(counts.moderate ?? 0)}, high=${high}, critical=${critical}`,
);

if (accepted.size > 0) {
  console.log(`Accepted, active exceptions: ${[...accepted].join(", ")}`);
}

if (unresolved.length > 0) {
  console.error(
    `Unaccepted high or critical production vulnerabilities in ${cwd}:\n` +
      unresolved.map((item) => `- ${item}`).join("\n"),
  );
  process.exit(1);
}

if ((high > 0 || critical > 0) && accepted.size === 0) {
  console.error(`npm audit totals and advisory details disagree in ${cwd}.`);
  process.exit(1);
}
