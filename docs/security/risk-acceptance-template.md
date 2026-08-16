# Security risk acceptance

> Copy this file into the relevant incident, pilot, or decision folder. A risk
> acceptance is temporary evidence of an informed decision; it is not a waiver of
> engineering responsibility or a substitute for remediation.

## Record

| Field | Value |
| --- | --- |
| Risk ID | `RISK-YYYY-NNN` |
| Title | TBD |
| Date opened | YYYY-MM-DD |
| Expiry/review date | YYYY-MM-DD |
| Environment | local / staging / pilot / production |
| Tenant/workflow scope | TBD |
| Asset/data class | TBD |
| Related issue/incident | TBD |
| Technical owner | TBD |
| Business owner | TBD |
| Security/privacy reviewer | TBD |

## Risk statement

Describe the condition, threat actor, exploit path, affected assets, and customer
or business impact in concrete terms.

## Evidence and confidence

- What was observed or tested?
- What remains unknown?
- Is exploitation known, suspected, or theoretical?
- Which commit, deployment, configuration, provider, and runbook versions are affected?

## Severity

- Likelihood: low / medium / high
- Impact: low / medium / high / critical
- Overall severity: low / medium / high / critical

A known active exploit, tenant-isolation failure, or unauthorized financial,
destructive, or irreversible action may not be accepted for a production-like
pilot.

## Current controls

List the controls that reduce likelihood or impact and attach evidence that they
work.

## Temporary mitigation

State exactly what is disabled, restricted, monitored, or manually reviewed.
Include rollback/disable instructions and operational ownership.

## Detection

Define the alert, log query, review, or manual check that detects exploitation or
control failure. Include expected response time.

## Remediation plan

| Action | Owner | Due date | Verification |
| --- | --- | --- | --- |
| TBD | TBD | YYYY-MM-DD | Test, review, or deployment evidence |

## Customer/contract impact

- Does the accepted risk conflict with a customer agreement, DPA, security
  statement, or pilot success criterion?
- Does the customer need to approve or be informed?
- Is processing required to pause until approval?

## Approval

By approving, the signatories confirm that they understand the scope, impact,
mitigation, detection, and expiry. The risk automatically returns to review on
expiry or when the condition changes.

| Role | Name | Decision | Date |
| --- | --- | --- | --- |
| Engineering owner | TBD | approve / reject | YYYY-MM-DD |
| Business owner | TBD | approve / reject | YYYY-MM-DD |
| Security/privacy reviewer | TBD | approve / reject | YYYY-MM-DD |
| Customer owner, when required | TBD | approve / reject | YYYY-MM-DD |

## Closure

Record remediation evidence, residual risk, closure approvers, and the date the
temporary mitigation was removed.
