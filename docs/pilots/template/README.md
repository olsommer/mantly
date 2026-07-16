# Design-partner pilot evidence workspace

Copy this directory to `docs/pilots/<approved-or-anonymized-pilot-id>/` or to the
approved restricted evidence repository before the pilot starts. Do not commit
customer message bodies, attachments, credentials, personal data, or contractual
confidential information to this repository.

## Required files

```text
targets.yml                 approved copy of docs/pilot-targets.example.yml
ticket-metrics.ndjson       one privacy-minimized metric record per included/excluded ticket
baseline.csv                comparable historical baseline
report.md                   narrative evidence and limitations
decision.yml                explicit customer/economic-buyer outcome
risk-register.md            open, accepted, and closed pilot risks
summary.json                generated KPI result
summary.md                  generated human-readable KPI table
```

Detailed or sensitive evidence should be stored in the approved access-controlled
location and referenced with stable IDs in the metric records/report.

## Before go-live

1. Complete `targets.yml`; every owner, date, runbook version, target, approval,
   exclusion, and pause condition must be resolved.
2. Capture the baseline using the same inclusion/exclusion and cost assumptions.
3. Validate synthetic metric records against `docs/pilot-metrics-schema.json`.
4. Confirm security, CI, recovery, privacy, incident, and lifecycle gates are
   closed or have time-bounded risk acceptance.
5. Run:

```bash
cd backend
uv run python ../scripts/pilot-evidence.py validate \
  ../docs/pilots/<pilot-id> \
  --allow-incomplete-sample
```

Use `--allow-incomplete-sample` only for synthetic/preflight data or a documented
approved sample exception. Do not use it to make final pilot evidence pass.

## During the pilot

- append one immutable NDJSON record version for every eligible or excluded ticket;
- preserve source/audit evidence through permission-controlled references;
- review 100% of critical/failed/recovered tickets and the approved quality sample;
- pause affected automation on a configured stop condition;
- record runbook/provider/configuration changes and do not rewrite earlier evidence;
- keep a risk and deviation log with owners and decisions;
- leave autonomous candidates in observation until the configured window closes.

## Final validation and summary

```bash
cd backend
uv run python ../scripts/pilot-evidence.py validate ../docs/pilots/<pilot-id>
uv run python ../scripts/pilot-evidence.py summarize ../docs/pilots/<pilot-id>
```

The generated summary calculates sample/exclusions, verified automation, match
precision/coverage, unsafe and critical outcomes, response/resolution timing,
action failures/recovery, recurring cost reduction, runbook breakdown, target
pass/fail, and commercial decision.

A green generated summary is necessary but not sufficient. The final report must
explain confidence limits, every major/critical error, operator/customer feedback,
reliability events, deviations, and the economic buyer's decision.

## Closure

Issue #6 remains open until a real design-partner report exists and the customer
selects one of:

- pay and continue;
- commercial trial;
- expand;
- iterate and repeat;
- pause;
- stop or reject.

Synthetic fixtures and repository tooling prove the measurement process, not
product-market fit.
