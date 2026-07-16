# Pilot success criteria

Status: **Required before real-ticket processing**

Owner: Product owner with design-partner operational owner

This document defines how the first Mantly design-partner pilot is measured. It
must be completed with customer-specific targets before production traffic is
included. Targets may not be rewritten after results are known without retaining
the original target and recording the reason.

## 1. Pilot decision

The pilot answers one question:

> Does Mantly safely reduce human support work for the selected email workflow
> enough that the customer wants to continue, pay, or expand?

Technical onboarding is a prerequisite, not a successful outcome.

## 2. Minimum evidence set

The default pilot evidence set is:

- at least **200 real, eligible tickets**;
- one email queue or mailbox;
- the three runbooks defined in `docs/v1-scope.md`;
- a pre-pilot baseline from at least four representative weeks or an equivalent
  historical sample;
- a minimum observation window of seven calendar days after an automated outcome
  for customer corrections or manual recovery;
- separate reporting for each runbook and for no-match/manual tickets.

A smaller sample requires a written exception before the pilot begins. The
exception must explain the expected ticket volume, the confidence limitation,
and the decision that can still be made from the smaller sample.

## 3. Ticket population

### Included tickets

A ticket is eligible when:

- it entered through the selected pilot mailbox;
- it belongs to the selected workflow;
- the customer message and attachments are accessible under the pilot agreement;
- it arrived during the agreed measurement window;
- it was not created solely for testing or training.

### Excluded tickets

Exclude only tickets matching a predeclared rule, such as:

- spam or malware;
- duplicate ingestion of the same source message;
- an outage that made the source system unavailable for all handling modes;
- a request outside the selected workflow;
- a customer withdrawal or legally required deletion before evaluation.

Every exclusion requires a machine-readable reason. Exclusions are reported by
count and percentage and may not be used to hide difficult in-scope tickets.

## 4. Handling classifications

Each ticket receives exactly one final handling classification.

| Classification | Definition |
| --- | --- |
| **Verified autonomous** | No human changed the match, actions, response, or delivery decision; required actions and delivery succeeded; no correction or recovery occurred during the observation window; quality review passed. |
| **Assisted** | Mantly matched, researched, acted, or drafted, but a human approved, edited, triggered, or completed material work. |
| **Manual** | Mantly routed the ticket to a human without materially completing the work. |
| **Failed automation** | Automation started but stopped because of technical failure, policy boundary, unsafe output, or incomplete action. The ticket may later be resolved manually. |
| **Invalid/excluded** | The ticket met a predeclared exclusion rule. |

A draft accepted without edits remains assisted handling unless the pilot contract
explicitly defines human approval as non-material. It never counts as verified
autonomous handling.

## 5. Primary KPIs

### 5.1 Verified full-automation rate

```text
verified autonomous tickets / all eligible tickets
```

Report overall, by runbook, by week, and with the no-match population visible.

Customer-specific target: `TBD before pilot`

Default evidence threshold for a first controlled pilot: **at least 20% overall**
with no safety threshold breach. This is a learning threshold, not a commercial
promise.

### 5.2 Cost per resolved ticket

```text
(total human handling cost + Mantly variable cost + allocated pilot operations cost)
/ resolved eligible tickets
```

Report baseline and pilot periods using the same labour-rate assumption. Separate
one-time onboarding cost from recurring operating cost.

Customer-specific target: `TBD before pilot`

Default evidence threshold: **at least 15% recurring cost reduction** for the
selected workflow or a credible measured path to that reduction.

### 5.3 Unsafe or materially incorrect outcome rate

```text
eligible tickets with an unsafe or materially incorrect Mantly outcome
/ eligible tickets where Mantly materially influenced the outcome
```

Unsafe or materially incorrect includes:

- an unauthorized action;
- a policy-contradicting action or answer;
- disclosure to the wrong customer or tenant;
- an irreversible action without required approval;
- a fabricated material fact or policy basis;
- delivery of content that requires immediate manual correction;
- duplicate side effects.

Target: **0 critical outcomes**. Any critical outcome pauses the affected runbook
until review and explicit reapproval.

### 5.4 Customer continuation signal

At pilot close, the economic buyer or authorized operational owner must select one:

- pay and continue;
- continue under an agreed commercial trial;
- expand scope;
- iterate and repeat the pilot;
- pause;
- stop/reject.

A positive continuation signal is `pay`, `commercial trial`, or `expand`.

## 6. Secondary KPIs

### 6.1 Runbook match precision

```text
correct selected runbook / tickets where Mantly selected a runbook
```

A correct match is determined from the final reviewed ticket outcome. Report
false-positive matches separately because they carry greater automation risk than
no-match routing.

Target: `TBD before pilot`; default minimum for any automatic path: **95%**.

### 6.2 Runbook match coverage

```text
tickets with a selected runbook / eligible tickets
```

Coverage is not optimized at the expense of precision. No-match/manual routing is
an acceptable safe outcome.

### 6.3 Draft acceptance rate

```text
responses sent with no material human edit / responses drafted by Mantly
```

Also report minor edits and major rewrites. Define material edit before the pilot
using either semantic review or an agreed edit-distance proxy.

### 6.4 Human escalation rate

```text
eligible tickets requiring human handling / eligible tickets
```

Break down by no match, policy boundary, missing data, approval requirement,
technical failure, and quality/safety block.

### 6.5 First-response time

Measure from source-channel receipt to the first customer-visible response. Report
median, p90, and p95 for baseline and pilot.

### 6.6 Resolution time

Measure from source-channel receipt to the final resolved state. Report median,
p90, and p95. Reopened tickets retain the original start time.

### 6.7 Failed-action rate

```text
tickets with at least one failed external action / tickets with an attempted action
```

Report transient failures, retry exhaustion, policy blocks, and partial side
effects separately.

### 6.8 Manual recovery rate

```text
verified-autonomous candidates requiring human recovery during observation
/ autonomous candidates
```

An outcome is not verified autonomous until the observation window closes.

### 6.9 Variable AI and delivery cost

Report per ticket and per verified autonomous resolution:

- model input/output tokens and provider cost;
- tool/API cost where measurable;
- message delivery cost;
- retry cost;
- managed-provider markup separately from underlying provider cost.

## 7. Quality review

### Sampling

Review:

- 100% of failed automation, unsafe flags, customer corrections, and manual
  recoveries;
- 100% of autonomous outcomes for the first 50 eligible tickets;
- after the first 50, at least 20% of autonomous outcomes with stratified sampling
  across all three runbooks;
- at least 10% of assisted outcomes;
- a random sample of no-match/manual outcomes to detect avoidable misses.

### Review dimensions

Score each reviewed outcome on:

- correct intent/runbook;
- correct customer and business context;
- policy grounding;
- factual correctness;
- action correctness;
- permission and approval compliance;
- response completeness;
- tone and approved language;
- disclosure compliance;
- delivery success;
- trace completeness.

Use a four-level result: `pass`, `minor issue`, `major issue`, `critical issue`.
The reviewer records evidence and an error category, not only a score.

## 8. Data contract

Each eligible ticket must expose or export at least:

| Field | Purpose |
| --- | --- |
| `ticket_id` | Stable, tenant-scoped identifier. |
| `source_message_id` | Duplicate detection and source trace. |
| `received_at`, `first_response_at`, `resolved_at` | Time metrics. |
| `runbook_id`, `runbook_version`, `match_confidence` | Match evaluation. |
| `handling_classification` | Primary outcome. |
| `human_touch_count`, `approval_required`, `material_edit` | Assistance measurement. |
| `action_attempts`, `action_failures`, `duplicate_side_effect` | Execution quality. |
| `delivery_status`, `delivery_attempts` | Customer-visible completion. |
| `review_result`, `review_categories` | Quality and safety evidence. |
| `observation_window_end`, `recovery_required` | Autonomous verification. |
| `model_provider`, `model_name`, `input_tokens`, `output_tokens`, `llm_cost` | Variable cost. |
| `exclusion_reason` | Population integrity. |

Sensitive customer content is not required in the metrics export. Evidence can be
referenced by permission-controlled IDs.

## 9. Baseline method

Before the first real pilot ticket:

1. select a representative historical period;
2. apply the same inclusion/exclusion rules;
3. classify tickets by the three intended runbooks and no-match;
4. estimate or measure handling time and labour cost consistently;
5. record first-response and resolution times;
6. record reopen/correction rates where available;
7. document missing baseline data and the chosen proxy.

The baseline dataset and assumptions are versioned with the pilot report.

## 10. Pre-pilot approval record

Complete this table in the customer-specific pilot folder before go-live.

| Item | Approved value |
| --- | --- |
| Customer/design-partner identifier | TBD |
| Operational owner | TBD |
| Economic buyer | TBD |
| Pilot start/end | TBD |
| Mailbox/queue | TBD |
| Expected eligible volume | TBD |
| Runbooks and versions | TBD |
| Full-automation target | TBD |
| Cost-reduction target | TBD |
| Match-precision target | TBD |
| Observation window | TBD |
| Human-review sample | TBD |
| Critical pause conditions | 0 critical unsafe/materially incorrect outcomes |
| Approved exclusions | TBD |
| Labour cost assumption | TBD |
| Commercial decision date | TBD |

## 11. Go/no-go rules

### Start real-ticket processing only when

- the V1 scope and three runbooks are approved;
- the baseline and target table are complete;
- security, privacy, recovery, and CI readiness are closed or have a documented
  risk acceptance;
- metric capture has passed a synthetic end-to-end test;
- the operational owner knows how to pause a runbook and route tickets manually.

### Pause a runbook immediately when

- a critical unsafe or materially incorrect outcome occurs;
- tenant isolation or unauthorized disclosure is suspected;
- duplicate irreversible side effects occur;
- required audit evidence is missing;
- the actual runbook version cannot be identified;
- delivery or action failures exceed the agreed operational threshold.

### Pilot pass

A pilot passes only when:

- no critical safety threshold was breached without completed remediation and
  reapproval;
- the agreed automation, cost, quality, and operational thresholds are met or the
  customer accepts a documented iteration plan;
- the results are reproducible from the exported evidence;
- the customer gives an explicit continuation decision.

## 12. Reporting

The final report must include:

- scope and deviations;
- sample and exclusions;
- baseline and pilot KPI table;
- runbook-level results;
- confidence limitations;
- all major/critical errors and remediation;
- reliability and recovery events;
- agent/operator feedback;
- customer decision;
- prioritized follow-up work tied to evidence.

Use `docs/pilots/template/` once the pilot evidence package is merged.
