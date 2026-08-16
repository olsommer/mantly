# Pilot success criteria

Status: **Required before real-ticket processing**

Owner: Product owner with the design-partner operational owner

This document defines the measurement and pass/fail contract for the first
Mantly design-partner pilot. Copy `docs/pilot-targets.example.yml` into the
customer-specific pilot folder, replace every placeholder, approve it before
go-live, and retain that approved version. Targets may be tightened before
approval. They may never be deleted, set to `null`, or rewritten after results
are known.

## 1. Pilot decision

The pilot answers one question:

> Does Mantly safely reduce human support work for the selected email workflow
> enough that the customer wants to continue, pay, or expand?

Technical onboarding is a prerequisite, not a successful outcome.

## 2. Minimum evidence set

A valid pilot contains:

- at least **200 real, eligible tickets**;
- one selected email queue or mailbox;
- exactly the three runbooks in `docs/v1-scope.md`;
- a pre-pilot baseline covering at least four representative weeks;
- at least seven calendar days of observation after each autonomous outcome;
- separate results for each runbook and the no-match/manual population;
- one final, schema-valid metric record for every included or excluded ticket;
- one approved target contract and one reproducible result summary.

A sample below 200 does not pass this pilot contract. It may produce learning,
but it must be reported as incomplete evidence and cannot be called a passed V1
pilot.

## 3. Ticket population

### Included tickets

A ticket is eligible only when:

- it entered through the selected pilot mailbox;
- it belongs to the selected workflow;
- its message and attachments are available under the pilot agreement;
- it arrived during the approved measurement window;
- it was not created for testing or training.

### Excluded tickets

Exclude only a ticket matching an approved machine-readable reason:

- `spam_or_malware`;
- `duplicate_ingestion`;
- `workflow_out_of_scope`;
- `source_system_outage`;
- `customer_withdrawal_or_deletion`;
- `synthetic_or_training`;
- `other_preapproved`, only when the exact rule was approved before go-live.

Report exclusion count and rate. An excluded record must not carry eligible
outcome fields. Difficult in-scope tickets remain in every eligible-ticket
denominator.

## 4. Handling and customer-decision outcomes

Each ticket has exactly one schema value:

| Value | Meaning |
| --- | --- |
| `verified_autonomous` | No human changed the match, actions, response, or delivery decision; all required actions and delivery succeeded; review passed; the observation window closed without correction or recovery. |
| `autonomous_candidate_observing` | The automatic path completed, but the observation window or required review remains open. This never counts as verified automation or a final pilot pass. |
| `assisted` | Mantly materially helped, but a human approved, edited, triggered, recovered, or completed work. |
| `manual` | Mantly routed the ticket without materially completing work. |
| `failed_automation` | Automation started but stopped because of technical failure, policy boundary, unsafe output, or incomplete action. |
| `excluded` | The record has `eligibility: excluded` and an approved exclusion reason. |

A human-approved draft is assisted even when sent without edits.

The customer decision is exactly one of `pay`, `continue`, `expand`, `iterate`,
`pause`, or `stop`. `pay`, `continue`, and `expand` map to continuation score
`1`; all other valid decisions map to `0`. Missing, `null`, free-text, and
unknown outcomes are invalid.

## 5. Calculation rules

- A rate denominator of zero is missing evidence, never `0%` or `100%`.
- Missing, `null`, non-finite, or unknown KPI values fail evaluation.
- Time starts at immutable source receipt. Reopened tickets retain the original
  start time.
- P90 uses the nearest-rank method on all eligible final records:
  sorted value at rank `ceil(0.90 * count)`.
- Baseline and pilot cost use the same population rules, EUR labour rate, and
  allocation method.
- Recurring pilot cost per resolved ticket equals `(human_minutes / 60 *
  labour_cost_per_hour + llm_cost + tool_and_delivery_cost + allocated recurring
  pilot operations cost) / resolved eligible tickets`.
- One-time onboarding cost is reported separately and excluded from recurring
  cost reduction.
- Every result is computed from schema- and semantic-valid records. Invalid
  records remain visible as validation failures; they are not silently dropped.

## 6. KPI contract

The YAML key is canonical for validation and reporting. Each target is numeric,
owned, and tied to a named source in `docs/pilot-targets.example.yml`.

### Primary KPIs

| YAML key | Formula | Data source | Accountable owner | Default target |
| --- | --- | --- | --- | --- |
| `verified_full_automation_rate` | `verified_autonomous eligible tickets / all eligible tickets` | Validated metric export: `eligibility`, `handling_classification` | Pilot metrics owner | `>= 0.20` |
| `recurring_cost_reduction_rate` | `(baseline recurring cost per resolved ticket - pilot recurring cost per resolved ticket) / baseline recurring cost per resolved ticket` | Approved baseline plus validated `human_minutes`, `llm_cost`, `tool_and_delivery_cost` | Finance owner | `>= 0.15` |
| `unsafe_or_materially_incorrect_outcome_rate` | `eligible tickets marked unsafe_or_materially_incorrect / eligible tickets where Mantly materially influenced handling` | Validated metric export and required quality review | Safety review owner | `<= 0.00` |
| `customer_continuation_score` | `1` for `pay`, `continue`, or `expand`; otherwise `0` | Signed pilot-close customer decision | Economic buyer | `>= 1` |

### Secondary KPIs

| YAML key | Formula | Data source | Accountable owner | Default target |
| --- | --- | --- | --- | --- |
| `runbook_match_precision` | `correct selected-runbook reviews / all reviewed tickets with a selected runbook` | `runbook_id`, `runbook_version`, `match_review` | Runbook owner | `>= 0.95` |
| `runbook_match_coverage` | `eligible tickets with a selected runbook / all eligible tickets` | `eligibility`, `runbook_id` | Runbook owner | `>= 0.50` |
| `draft_acceptance_rate` | `delivered drafted responses with material_edit=false / all delivered drafted responses` | `draft_generated`, `material_edit`, `delivery_status` | Support operations owner | `>= 0.70` |
| `human_escalation_rate` | `eligible tickets with human_touch_count>0 or assisted/manual handling / all eligible tickets` | `human_touch_count`, `handling_classification` | Support operations owner | `<= 0.80` |
| `first_response_time_p90_seconds` | P90 of `first_response_at - received_at` for eligible tickets | Required timestamps in validated metric export | Support operations owner | `<= 3600` |
| `resolution_time_p90_seconds` | P90 of `resolved_at - received_at` for eligible tickets | Required timestamps in validated metric export | Support operations owner | `<= 86400` |
| `failed_action_rate` | `eligible tickets with action_failures>0 / eligible tickets with action_attempts>0` | `action_attempts`, `action_failures` | Engineering owner | `<= 0.05` |
| `manual_recovery_rate` | `autonomous candidates with recovery_required=true / all autonomous candidates` | `autonomous_candidate`, `recovery_required` | Support operations owner | `<= 0.02` |
| `variable_ai_and_delivery_cost_per_eligible_ticket_eur` | `sum(llm_cost + tool_and_delivery_cost) / eligible tickets` | Validated cost fields | Finance owner | `<= 1.00` |
| `variable_ai_and_delivery_cost_per_verified_autonomous_ticket_eur` | `sum(llm_cost + tool_and_delivery_cost) / verified autonomous tickets` | Validated cost and classification fields | Finance owner | `<= 5.00` |
| `quality_review_pass_rate` | `review_result=pass / all completed required reviews` | Required review sample joined to metric export | Quality review owner | `>= 0.95` |

The default numbers are precommitment values for the first DACH email pilot,
not external product promises. A customer-specific contract may tighten or
replace a numeric value before approval, but every key, owner, source, and
numeric target remains required.

## 7. Non-negotiable guards

Every guard is evaluated in addition to every KPI.

| YAML key | Required result | Source | Owner |
| --- | --- | --- | --- |
| `critical_outcome_count` | `<= 0` | Metric export: `critical_outcome` | Safety review owner |
| `unsafe_or_materially_incorrect_outcome_count` | `<= 0` | Metric export: `unsafe_or_materially_incorrect` | Safety review owner |
| `tenant_isolation_incident_count` | `<= 0` | Incident register and isolation review | Security owner |
| `duplicate_irreversible_side_effect_count` | `<= 0` | Action traces and incident register | Engineering owner |
| `schema_validation_error_count` | `<= 0` | Evidence validator output | Pilot metrics owner |
| `semantic_validation_error_count` | `<= 0` | Evidence validator output | Pilot metrics owner |
| `missing_required_evidence_count` | `<= 0` | Final evidence audit | Pilot metrics owner |
| `unknown_outcome_count` | `<= 0` | Schema validation and outcome reconciliation | Pilot metrics owner |
| `unresolved_eligible_ticket_count` | `<= 0` | Required `resolved_at` and final handling values | Support operations owner |
| `required_review_sample_completion_rate` | `>= 1.00` | Review sampling ledger | Quality review owner |

A critical outcome, suspected isolation incident, duplicate irreversible side
effect, missing execution trace, or unknown runbook/outcome pauses the affected
runbook immediately. Remediation permits a new approved pilot iteration; it does
not retroactively convert a failed result into a pass.

## 8. Quality review

Review:

- 100% of failed automation, safety flags, corrections, and recoveries;
- 100% of the first 50 eligible tickets;
- after ticket 50, at least 20% of autonomous outcomes, stratified across all
  three runbooks;
- at least 10% of assisted outcomes;
- at least 10% of manual/no-match outcomes.

Use exactly `pass`, `minor_issue`, `major_issue`, or `critical_issue` for a
completed review; use `not_reviewed` only outside the required sample. Record
categories and evidence references. A required sampled ticket marked
`not_reviewed` makes review completion less than `1.00` and fails the guard.

Review runbook match, customer context, policy grounding, factual and action
correctness, permission/approval compliance, completeness, tone/language,
disclosure, delivery, trace completeness, and tenant isolation.

## 9. Ticket metric contract and validation

`docs/pilot-metrics-schema.json` is Draft 2020-12. It rejects `null` timing and
outcome fields, unknown or queued final delivery outcomes, mismatched
eligibility/classification, and incomplete verified-autonomous claims.

Semantic validation additionally rejects reversed timestamps, action failures
above attempts, inconsistent delivery attempts, incomplete runbook identity,
recovery without an autonomous candidate, and model usage without provider and
model evidence.

Validate the checked-in target template:

```bash
cd backend
uv run python -m automail.pilot_evidence \
  --targets ../docs/pilot-targets.example.yml \
  --allow-template-placeholders
```

Validate a completed pilot:

```bash
cd backend
uv run python -m automail.pilot_evidence \
  --targets ../docs/pilots/<pilot-id>/targets.yml \
  --results ../docs/pilots/<pilot-id>/results.yml \
  --metrics ../docs/pilots/<pilot-id>/ticket-metrics.jsonl
```

The command exits nonzero when any target, KPI, guard, evidence flag, schema
record, or semantic rule fails. `docs/pilot-results.example.yml` defines the
required result shape; its placeholder ID is intentionally not an approved
pilot record.

## 10. Instrumentation inventory

| Measurement surface | Current repository evidence | Pilot status |
| --- | --- | --- |
| Ticket counts/status plus average and P90 first-response/resolution time | Support Analytics reads issue and SLA timestamps. | **Partial**: usable for reconciliation, but the pilot export must preserve the frozen population and immutable receipt time. |
| AI-needs-human, action execution, failed automation, outbound, and delivery counts | Support Analytics and support records expose these operational counts. | **Partial**: not equivalent to the required per-ticket classification and review fields. |
| Model token usage and provider cost | LLM usage events and run metadata exist. | **Partial**: join to pilot/ticket IDs and export normalized EUR cost. |
| Eligibility, exclusion, final handling, autonomous candidate, material edit, match review, recovery, safety/critical review, and evidence references | No complete Analytics export currently exposes this contract. | **Missing blocker**: implement and validate under [issue #6](https://github.com/olsommer/mantly/issues/6) before real-ticket measurement. |
| Labour cost, baseline allocation, and customer continuation decision | Customer-approved baseline and signed closeout record. | **Manual source**: owner must approve and retain it with evidence. |

Existing Analytics is supporting evidence, not proof that every KPI is
instrumented. Real-ticket processing must not start until issue #6's export path
can produce schema- and semantic-valid records for synthetic happy, no-match,
failure, duplicate-delivery, and recovery cases.

## 11. Baseline method

Before the first real ticket:

1. select at least four representative historical weeks;
2. apply the same inclusion and exclusion rules;
3. classify the three runbooks and no-match population;
4. measure handling minutes and use the approved EUR labour rate;
5. calculate first-response and resolution times using the same timestamp rules;
6. calculate recurring cost per resolved ticket;
7. record every source, assumption, proxy, and missing field;
8. obtain product, finance, and customer operational approval.

A zero or missing baseline cost cannot support cost-reduction pass.

## 12. Go/no-go and pass/fail

### Start real-ticket processing only when

- the V1 scope, mailbox, runbook versions, baseline, and completed target file
  are approved;
- all target and guard entries contain a numeric target, owner, and data source;
- security, privacy, recovery, and CI readiness are accepted;
- synthetic records pass schema and semantic validation;
- the instrumentation blocker in issue #6 is resolved for the pilot export;
- operators can pause a runbook and route tickets manually.

### Pilot pass

A pilot passes only when all conditions are true:

1. at least 200 eligible tickets have final, valid records;
2. every required KPI value is present, finite, reproducible, and meets its
   approved comparator and target;
3. every guard meets its approved comparator and target;
4. every required evidence flag is true;
5. no eligible ticket has a missing/null time, unresolved candidate state,
   unknown outcome, invalid enum, or validation error;
6. required quality-review sampling is 100% complete;
7. the customer decision is `pay`, `continue`, or `expand`.

No missing evidence defaults to good. No average can offset a failed safety or
quality guard. A customer-accepted iteration plan is a valid next decision, but
the current pilot remains failed/incomplete.

## 13. Reporting

The final report includes:

- approved scope, targets, owners, sources, and deviations;
- sample and exclusions;
- baseline and every KPI/guard result;
- per-runbook and no-match results;
- confidence limitations;
- every major/critical error and remediation;
- reliability, recovery, privacy, and security events;
- operator feedback;
- the signed customer decision;
- follow-up work tied to evidence.

Keep the approved targets, result YAML, validator output, privacy-minimized
metric export, and report together in the customer-specific pilot folder.
