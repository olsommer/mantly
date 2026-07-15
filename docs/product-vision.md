# Mantly Product Vision

Status: Draft

Last updated: 2026-07-15

This document defines Mantly's product direction. It describes the intended
product, not only the behavior implemented today. The
[Email-First Support System RFC](./pylon-pivot-rfc.md) remains the detailed
current implementation contract. Where the two conflict, this vision guides
future product decisions unless a later decision supersedes it.

## How to read this document

- **Vision** describes the intended product direction.
- **V1** describes the first product slice Mantly should validate, not a claim
  that every capability already ships.
- **Current implementation** remains documented in the linked RFC and source
  code.
- **Later** and **open research** are directions, not commitments.

## Positioning

**Category:** Agentic omnichannel customer support platform.

**Lead promise:** Customer support that runs itself.

Mantly is an omnichannel support system of record built around agentic
execution. Companies define how support should operate; Mantly matches incoming
tickets to executable runbooks, completes configured work, involves humans when
the runbook requires it, and sends the resulting answer through the originating
channel.

Mantly should win through:

- End-to-end agentic execution, not reply suggestions alone.
- A higher full-automation rate and lower cost per resolved ticket.
- Deep company control over runbooks, knowledge, permissions, and autonomy.
- Mantly Cloud plus an enterprise on-premises option.
- A likely self-hostable or source-available model, with the exact boundary
  still open.

The anti-vision is a Zendesk clone with an AI sidebar. Mantly must not become a
bloated legacy helpdesk checklist, a general-purpose workflow builder, or an
opaque AI system that acts without company control and an execution trace.

## Customer and problem

Mantly initially serves DACH companies with substantial customer-support
volume. Logistics, ecommerce, and insurance are useful examples, but the
product remains horizontal and does not embed industry-specific business logic.

The core problems are:

- High support cost.
- Slow responses and resolutions.
- Time lost finding the knowledge needed to answer or process a request.
- Customer communication fragmented across channels.

The likely runbook author is an operations specialist with light technical
skills. The economic buyer remains a research question.

## Outcome hierarchy

The primary product outcome is a higher full-automation rate, producing a lower
cost per resolved ticket.

Secondary outcomes are:

- Faster resolution.
- Better and more consistent answer quality.
- Fewer avoidable human escalations.

Dashboard hierarchy follows the same order:

1. Automation rate.
2. Estimated cost savings.
3. Exceptions requiring attention.
4. System health.

## Product model

Mantly has three product pillars.

| Pillar | Purpose | Optionality |
| --- | --- | --- |
| **Inbox** | Omnichannel support inbox and system of record for tickets, conversations, actions, replies, ownership, and audit history. | Shared foundation. |
| **Runbook Agent** | Matches and activates executable support runbooks, performs configured work, and applies the runbook's human/automation behavior. | Independently enabled module. |
| **Knowledge Agent** | Helps a human investigate a ticket by searching permitted company knowledge and preparing a cited answer. | Independently enabled module. |

Both agents use one shared, permission-aware knowledge layer. They remain
different services with different triggers and permission models; they are not
one unified agent runtime.

The core product object is a **Ticket**. “Customer concern” can remain marketing
language, but the product UI uses the familiar ticket term.

## Core operating flow

```text
Customer channel
    -> normalized ticket in Inbox
    -> Runbook Agent selects one best-matching runbook
        -> manual handling
        -> semi-automatic handling
        -> automatic handling
    -> one customer response
    -> originating channel
```

For V1, one ticket activates one runbook. If a ticket clearly contains several
independent requests and no single runbook is a safe fit, Mantly routes it for
manual handling. Multi-runbook selection, parallel execution, conflict
resolution, and response synthesis are later capabilities.

When no runbook matches, Mantly can queue the ticket for manual work and, when
enabled, prepare a knowledge-backed answer. The company controls whether that
answer remains a draft or may be sent automatically.

## Runbook Agent

A runbook behaves like an agent skill. It tells Mantly when the skill applies,
which knowledge and tools it may use, which actions it can expose or execute,
and how a response should be handled.

The agent finds the best runbook, activates it, then follows the behavior
configured by the company. V1 supports three practical outcomes:

These outcomes define the target product contract. Existing runbook flags and
runtime behavior may approximate them, but they are not the final configuration
schema.

### Manual

- Mantly matches and activates the runbook.
- The runbook marks the ticket for manual checking.
- Automation stops at that boundary.
- A human continues through the ticket workspace.

### Semi-automatic

- Configured automatic actions run.
- Other configured actions appear as human-triggered buttons.
- The runbook may prepare a response draft.
- A human completes the work and sends the response; semi-automatic handling
  never auto-sends.

### Automatic

- Configured automatic actions run.
- Mantly generates and sends the response when auto-send is configured.
- No human participates unless execution fails.

Response behavior remains runbook-configurable: no response, prepare a draft,
or send automatically where the selected runbook outcome permits it.

V1 does not need a general conditional-policy engine. Runbook configuration
should remain understandable: human review, automatic versus human-triggered
operations, and response behavior.

If an automatic action fails, Mantly stops automation, preserves completed and
failed action context, and turns the ticket into manual work. A human may retry
an individual action, but V1 does not resume or continue the runbook as a
workflow state machine.

## Knowledge Agent

The Knowledge Agent is a ticket-scoped service for human support work. A user
opens a ticket and explicitly starts the agent when more information is needed.

The shared knowledge layer is a platform capability, distinct from the
user-facing Knowledge Agent. Runbooks and no-match fallback can use that layer
automatically; the Knowledge Agent itself remains human-triggered in V1.

The intended interaction resembles an agent working through a virtual knowledge
workspace: discover sources, search them, read relevant files or sections, and
return a cited answer. The `cat`/`grep`/virtual-filesystem analogy describes the
agentic research experience; the product need not expose literal shell commands
to users. This is a target interaction model, not a description of the simpler
ticket-agent retrieval implemented today.

For V1, the Knowledge Agent:

- Works inside a ticket, not as a standalone company assistant.
- Inherits the current user's knowledge permissions.
- Searches permitted SOPs, policies, contracts, help content, and prior support
  material.
- Returns sources, findings, missing information, and response assistance.
- Never gains business-action rights implicitly.

The Runbook Agent uses a broader company-wide automation knowledge role.
Business-action access is defined explicitly inside each runbook.

## Shared knowledge

The long-term goal is broad connector coverage. The first sources should favor
fast setup:

- Uploaded files.
- Websites and public help centers.
- Notion, Google Drive, and SharePoint when launch integration effort remains
  reasonable.

Synced knowledge must preserve permission levels. Knowledge access differs by
service identity: the human-triggered Knowledge Agent uses the current user's
rights; the Runbook Agent uses the shared automation role.

## Human workspace and approvals

The Inbox supports different filters and views rather than forcing one working
style on every company. Detailed role taxonomy can follow real customer
research.

The manual ticket drawer centers three surfaces:

```text
Conversation | Actions and response | Knowledge
```

Where explicit approval is required, V1 uses a shared reviewer queue:

- The company configures the queue.
- Any authorized reviewer may claim an item.
- The ticket assignee retains visibility but is not the exclusive reviewer.
- Unclaimed reviews escalate against an SLA.
- Specialist or per-runbook approval routing can come later.

## Company control

Company-wide policies inherit into both services and all runbooks, with local
overrides where useful. Shared policy includes:

- Brand voice.
- Approved languages.
- Knowledge and action permissions.
- AI disclosure.
- Default autonomy behavior.

Mantly detects the customer's language automatically, but responds only in
languages approved by the company. Unsupported languages route to a human.
Disclosure that a response was generated autonomously is company-configurable.

Runbooks and policies should support UI authoring first and version-controlled
configuration files for advanced teams.

## Responsibility and trust

The company owns its business rules and autonomy choices. Mantly owns faithful,
permission-safe, observable execution of those choices.

Mantly must provide:

- Permission enforcement.
- Durable audit history and execution traces.
- Idempotency protections for side-effecting operations.
- Retry and fallback behavior for technical failures.
- Clear reversibility metadata and rollback or compensating actions only when
  the external tool contract supports them.
- Data security and tenant isolation.
- Visible failure states; tickets must never disappear silently.

Technical failure follows this order:

```text
retry -> fallback -> stop automation -> preserve context -> route manual
```

Full trace data should be captured from the beginning even when the initial UI
shows only the evidence needed for the current decision.

## Controlled evolution

“Customer support that runs itself” does not mean a system configured once and
left static. Mantly should evolve continuously without silently changing
production behavior.

The learning loop is:

1. Mantly or a user detects a correction, gap, or repeated pattern.
2. The user explicitly chooses **Learn this**.
3. Mantly infers whether the target is a runbook, company policy, or knowledge
   article.
4. Mantly shows a proposed diff.
5. Affected evaluations run.
6. The company approves publication.

Automatic learning without an explicit user signal is outside V1. Later,
Mantly can analyze historical tickets and observe human work to propose new
runbooks or improvements.

## V1 golden paths

### Autonomous delivery exception

A customer writes through email, embedded web chat, or WhatsApp:

> My order is delayed. Please change the delivery address.

Mantly:

1. Normalizes the message into a ticket.
2. Identifies the customer and order.
3. Matches the delivery-exception runbook.
4. Searches permitted policy knowledge.
5. Checks the shipment API.
6. Changes the address or opens a carrier case as configured.
7. Applies the runbook's manual, semi-automatic, or automatic behavior.
8. Answers in an approved customer language.
9. Records the complete execution trace.

### Manual knowledge investigation

A customer asks an unusual question without a suitable runbook:

> Can we ship temperature-sensitive goods to Norway, and which documents are
> required?

Mantly:

1. Routes the ticket for manual work.
2. A support user starts the Knowledge Agent.
3. The agent searches permitted SOPs, carrier documents, the customer contract,
   and relevant past material.
4. It returns cited findings and identifies missing information.
5. It prepares response assistance.
6. The human edits and sends the answer.

## V1 scope

V1 should prove both golden paths and the system-of-record foundation around
them.

### Required product slice

- Inbox as the ticket system of record.
- Runbook Agent and ticket-scoped Knowledge Agent as independent modules.
- Launch channel priorities, not current readiness claims:
  - Email.
  - Embedded website chat/add-on.
  - WhatsApp.
  - Discord.
- Manual runbook authoring by an operations specialist.
- Runbook simulation/evaluation and explicit publication.
- Explicit behavior selection rather than a silent automation default.
- Permission-aware shared knowledge.
- Shared reviewer queue and manual ticket drawer.
- Execution traces, failure visibility, and individual action retry.
- Configurable language and AI-disclosure policies.
- Flexible Inbox filters and views.

### Same-day activation target

A new customer should achieve the first successful autonomous resolution on the
same day:

1. Connect one channel.
2. Add knowledge.
3. Create one runbook.
4. Connect one tool.
5. Replay a test ticket.
6. Publish.

### DACH trust baseline

- EU hosting and GDPR readiness.
- Data processing agreement.
- Role-based access control.
- Audit logs.
- SSO/SAML.
- Configurable data retention.

### Explicit V1 boundaries

- Do not expand existing automation features into a general workflow builder.
- No visual DAGs, nested orchestration, multi-runbook execution, or runbook
  resume engine.
- No voice or phone channel.
- No standalone internal Knowledge Agent.
- No runbook or connector marketplace.
- No vertical-specific business logic.
- No silent production learning.
- No historical-ticket or human-observation runbook generation.

## Go-to-market and deployment

Mantly initially targets DACH. The primary position is a replacement support
system of record. A secondary mode may integrate Mantly as an agentic layer over
an existing helpdesk where the integration cost is justified.

Adoption starts with a side-by-side pilot on one channel or queue. This does not
require full two-way helpdesk integration. Full migration follows only after the
pilot proves:

- Higher automation.
- Lower handling cost.
- Faster resolution.
- Stable or improved quality.

Mantly Cloud is the default deployment. Enterprise customers can deploy on
premises. Customers should retain model/provider choice, including bring-your-
own keys or models where supported.

## Success measures

Product success:

- Full-automation rate.
- Cost per resolved ticket.
- Resolution speed.
- Quality and stability.
- Exception volume.
- System health.

A working definition of a verified autonomous resolution is a ticket completed
without human handling, with required actions and delivery succeeding and no
immediate manual recovery. The quality threshold and observation window still
need definition before this becomes a billing or contractual metric.

Business success over the next year means paying customers and revenue. Numeric
targets remain open.

## Later roadmap

- Historical-ticket analysis that proposes runbooks.
- Observation of human handling that proposes improvements.
- Broader knowledge connectors.
- Multi-intent detection and multi-runbook execution.
- Parallel runbook processing, conflict handling, and one synthesized response.
- Specialist approval routing.
- Runbook and connector marketplace.
- Voice support.
- Mature system-of-record migrations and existing-helpdesk integrations.

## Open research and decisions

- Economic buyer and internal champion.
- Pricing model.
- Exact open-source or source-available boundary and license.
- Numeric customer and revenue targets.
- Role taxonomy and default views.
- Existing-helpdesk overlay scope and priority.
- Exact launch sequencing for Notion, Google Drive, and SharePoint.
- Cross-channel identity confidence and merge-suggestion UX. Wrong merges are
  considered worse than missed merges, so V1 should remain conservative.
- Quality definition and the evaluation threshold required for publication.
- Canonical runbook configuration schema for manual, semi-automatic, and
  automatic behavior.
- Idempotency, rollback, and compensation contracts for arbitrary external
  actions.
