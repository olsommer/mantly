# Mantly V1 Scope

Status: **Active product contract**

Owner: Product and engineering

Review cadence: After every design-partner pilot or material product decision

This document is the implementation boundary for the first validated Mantly release. It narrows the broader product vision to one customer segment, one operating workflow, one launch channel, and three runbooks. When another document describes a broader V1, this document controls until an explicit superseding decision is approved.

## 1. V1 objective

Mantly V1 must prove that a controlled, email-first support system can safely eliminate a measurable amount of repetitive support work while preserving answer quality, auditability, and human control.

The primary product outcome is:

> A higher verified full-automation rate that lowers cost per resolved ticket without increasing unsafe or incorrect outcomes.

V1 is not successful because it supports many channels or exposes many configuration surfaces. It is successful when one real customer repeatedly receives correct, policy-compliant outcomes with less human work.

## 2. Initial customer segment

The initial design-partner profile is a DACH business with:

- a dedicated customer-support or operations team;
- at least several hundred repetitive support emails per month;
- documented operating procedures or policies;
- one operational owner who can approve runbooks and evaluate outcomes;
- access to the systems required for the selected workflow;
- willingness to run a side-by-side, founder-led pilot.

The preferred first segment is **logistics or ecommerce operations with repetitive order and delivery requests**. This is a prioritization choice, not permanent vertical-specific product logic.

Insurance and other regulated segments remain candidates after the first pilot demonstrates the core execution and governance model.

## 3. Primary V1 workflow

The primary V1 workflow is **email-based order and delivery support**.

A customer email is normalized into a ticket. Mantly determines whether one of the published runbooks is a safe match, retrieves permitted context, performs only the actions allowed by that runbook, applies the configured review boundary, and prepares or sends one response through the originating email channel.

The end-to-end contract is:

```text
email received
  -> tenant and customer context resolved
  -> ticket created with immutable source reference
  -> exactly one runbook selected or ticket routed to manual handling
  -> permitted knowledge and tools used
  -> action and response policy enforced
  -> delivery attempted once through an idempotent queue
  -> complete execution trace retained
  -> outcome included in pilot metrics
```

## 4. Launch channel

### Required

- Email ingestion and reply delivery.
- Outlook add-in for founder-led onboarding, review, and draft assistance where required.
- Admin Inbox as the support system of record.

### Frozen for V1 validation

The following channels may remain in the repository, but are not part of the V1 acceptance contract and must not drive roadmap priority before the first pilot report:

- embedded web chat;
- WhatsApp;
- Slack;
- Microsoft Teams;
- Discord;
- Telegram;
- Messenger;
- SMS;
- voice or telephone.

A frozen channel may receive correctness or security fixes. New capability work requires one of:

1. evidence from the active pilot;
2. a signed design-partner requirement that cannot be met through email;
3. an approved update to this scope document.

## 5. Initial runbooks

V1 validates exactly three production-quality runbooks. Their final names can follow the design partner's terminology, but they must represent these operating patterns.

### Runbook A: Delivery status request

**Intent:** A customer asks where an order or shipment is.

**Minimum behavior:**

- identify the customer and order or request missing identifiers;
- retrieve shipment status from an approved system;
- apply the company's communication policy;
- prepare or send a response according to the configured autonomy level;
- route exceptions and ambiguous matches to manual handling.

### Runbook B: Delivery address change

**Intent:** A customer asks to change a delivery address.

**Minimum behavior:**

- identify the order and current shipment state;
- check whether the change is permitted by company policy and carrier state;
- require human approval unless the customer and policy conditions are fully satisfied;
- execute through an idempotent tool contract;
- preserve before-state, action result, and reversibility metadata;
- stop automation on any uncertainty or partial failure.

### Runbook C: Cancellation or refund eligibility

**Intent:** A customer asks to cancel an order or requests a refund.

**Minimum behavior:**

- identify the order and applicable policy;
- determine eligibility without inventing policy;
- prepare a cited explanation and the next permitted action;
- require human approval for financial or irreversible action in the first pilot;
- record the decision basis and all tool calls.

## 6. Required product slice

The following capabilities are required for the V1 pilot contract.

### System of record

- Tenant-isolated tickets, messages, attachments, notes, ownership, status, and audit history.
- Reliable email ingestion with duplicate detection and replay protection.
- Outbound delivery queue with idempotency, retry limits, and visible failure state.
- Admin Inbox views sufficient to claim, review, respond to, and close tickets.

### Runbook governance

- One best-matching runbook or explicit no-match/manual routing.
- Draft, manual, semi-automatic, and automatic boundaries that are understandable to an operations owner.
- Versioned runbooks with explicit publication.
- Simulation or evaluation before publication.
- Per-runbook knowledge and action permissions.
- Human approval for configured high-risk actions.

### Knowledge and response quality

- Retrieval only from permitted knowledge sources.
- Source references retained for material policy or factual claims.
- Clear uncertainty and missing-information behavior.
- Language restricted to company-approved languages.
- Configurable AI disclosure.

### Trust and operations

- Tenant isolation and role enforcement.
- Durable action and decision trace.
- Idempotency for side-effecting operations.
- Visible retry, fallback, and manual-routing behavior.
- Security, retention, backup, recovery, and incident procedures required by the pilot-readiness epic.
- Metrics required by `docs/pilot-success-criteria.md` once that document is merged.

## 7. Explicit non-goals

The following are outside V1 unless this contract is deliberately changed:

- a general-purpose workflow builder;
- visual DAG authoring;
- nested or parallel runbook orchestration;
- multiple runbooks executing for one ticket;
- automatic production learning from human behavior;
- a connector or runbook marketplace;
- voice support;
- a standalone internal-company assistant;
- broad CRM replacement;
- advanced custom reporting unrelated to pilot metrics;
- complex billing optimization;
- autonomous financial or irreversible actions without an approved risk boundary;
- broad self-service onboarding before the founder-led pilot is repeatable.

## 8. Existing feature classification

Every existing or proposed feature should be placed in one of four classes.

| Class | Meaning | Allowed work before pilot evidence |
| --- | --- | --- |
| **Pilot required** | Necessary for the workflow, three runbooks, trust baseline, or measurement contract. | Build, test, and harden. |
| **Retained but frozen** | Existing functionality that is not required for the pilot. | Security, correctness, and maintenance only. |
| **Deferred** | Planned capability with no current implementation dependency. | Documentation and research only. |
| **Removal candidate** | Complexity that conflicts with V1 or has no validated owner or use case. | Preserve only when removal risk exceeds maintenance cost. |

New feature issues must state their class and evidence.

## 9. Definition of a verified autonomous resolution

A ticket counts as a verified autonomous resolution only when all of the following are true:

- no human changed the selected runbook, action plan, response, or delivery decision;
- all required actions completed successfully;
- the response was delivered successfully;
- no immediate manual recovery or customer correction was required during the configured observation window;
- the ticket passed the quality and safety review rules defined for the pilot;
- the execution trace is complete enough to reproduce the decision path.

A generated draft, partial action, or human-approved response is assisted handling, not full automation.

## 10. Scope-change process

A proposed scope change must include:

1. the customer or operational evidence;
2. the measurable outcome it improves;
3. the added security and reliability boundary;
4. the impact on the three-runbook pilot;
5. what will be removed, frozen, or delayed in exchange.

Approval requires the product owner and engineering owner. Material changes update this document, the pilot success criteria, and the roadmap epic.

## 11. V1 exit criteria

V1 is validated only when:

- one design partner completes the founder-led pilot;
- the selected workflow and all three runbooks process the agreed real-ticket sample;
- success is evaluated against precommitted metrics and thresholds;
- unsafe and incorrect outcomes are documented and within the accepted boundary;
- backup restoration and incident procedures have been exercised;
- the customer gives an explicit continue, pay, expand, pause, or stop decision;
- the team decides the next roadmap from measured evidence.

Until these conditions are met, broader channel coverage is product inventory, not proof of product-market fit.
