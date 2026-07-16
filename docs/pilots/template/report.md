# Pilot report — REPLACE PILOT ID

Status: draft / final

Evidence cutoff: YYYY-MM-DDTHH:MM:SSZ

Report owner: TBD

Independent reviewer: TBD

## Scope and deviations

Describe the approved customer segment, mailbox, workflow, three runbooks and
versions, providers, tools, autonomy boundaries, pilot window, observation window,
and every deviation from `targets.yml`. State whether the deviation was approved
before or after it occurred.

## Sample and exclusions

Document total records, eligible tickets, excluded tickets by approved reason,
runbook/no-match distribution, missing data, sampling limitations, and confidence
limits. Explain any approved sample-size exception.

## Baseline

Describe the historical period, inclusion/exclusion equivalence, labour-rate and
cost assumptions, first-response/resolution distributions, data gaps, and any
proxy. Link the validated `baseline.csv` and evidence references.

## KPI results

Paste or link `summary.md` and explain:

- verified full-automation rate;
- recurring cost per resolved ticket and reduction;
- runbook match precision and coverage;
- unsafe/materially incorrect rate and critical outcomes;
- first-response and resolution time;
- action/delivery failures and manual recovery;
- whether every precommitted target passed.

Do not hide a failed target behind aggregate success or change a target after
seeing the result.

## Runbook results

For each of the three published runbooks, report volume, verified autonomous,
assisted, manual, failed, match precision, action/delivery failures, reviews,
customer corrections, and the recommended autonomy change.

### Runbook 1 — TBD

### Runbook 2 — TBD

### Runbook 3 — TBD

### No-match/manual population

Explain whether safe no-match routing was appropriate and whether meaningful
coverage was missed.

## Safety and quality

List every major and critical review outcome, false-positive match, unauthorized
or duplicate action, policy/factual error, customer correction, privacy/security
event, and missing audit trace. Include root cause, containment, affected runbook,
regression evidence, reapproval, and residual risk.

State explicitly whether zero critical outcomes was maintained.

## Reliability and recovery

Report provider outages, queue age, retries, duplicate/replay events, unknown
external outcomes, scheduler/worker incidents, backup freshness, restore drill,
incident tabletop, latency/cost anomalies, and manual recovery workload.

## Operator and customer feedback

Summarize support-agent, operational-owner, end-customer (where collected),
security/privacy, and economic-buyer feedback. Separate direct feedback from team
interpretation.

## Commercial decision

Record the decision from `decision.yml`, who made it, date, commercial terms or
next decision gate, the evidence they reviewed, and conditions. A vague statement
such as “interested” is not an explicit continuation signal.

## Follow-up work

Prioritize work by evidence and impact:

1. safety/correctness blockers;
2. reliability/operability blockers;
3. changes that materially improve automation or cost for the validated workflow;
4. customer-specific expansion;
5. deferred platform/channel ideas.

Link issues with owner, priority, target release, and the pilot evidence they
address.

## Approval

| Role | Name | Decision | Date |
| --- | --- | --- | --- |
| Product owner | TBD | approve/reject | YYYY-MM-DD |
| Engineering owner | TBD | approve/reject | YYYY-MM-DD |
| Security/privacy owner | TBD | approve/reject | YYYY-MM-DD |
| Customer operational owner | TBD | approve/reject | YYYY-MM-DD |
| Economic buyer | TBD | approve/reject | YYYY-MM-DD |
