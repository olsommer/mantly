# Support Admin Progressive Disclosure Design

Date: 2026-07-06

## Purpose

The support admin app is moving toward an owned Pylon-like product: many inbound
channels, tickets as the system of record, AI-assisted handling, and human
approval where needed. The current Channel setup, Accounts, and Analytics
surfaces already expose much of this platform, but they show setup, operations,
diagnostics, and raw evidence at the same level.

This design keeps the existing feature set and makes the product easier to use
by adding progressive disclosure with shadcn primitives:

- `Dialog` for bounded tasks.
- `Sheet` for inspection and evidence.
- `Tabs` or segmented navigation for alternate analytical views.

## Current Evidence

Live DOM review showed the overload:

- Channel setup: about 9k characters of text and 69 actions, with provider setup,
  current cursors, sync history, webhook inbox, web chat sessions, delivery
  history, queues, CRM connectors, CRM sync history, and CRM webhook inbox on
  one route.
- Accounts: account list and detail work, but account detail mixes account
  health, insight editing, CRM health, external records, and recent issues in
  one surface.
- Analytics: about 8k characters of text and 62 actions, mixing launch readiness,
  launch proof, schema health, channel remediation, workload, SLA, status,
  priority, channel, queue, and assignee metrics.

Code review matched the DOM evidence:

- `admin/src/routes/Channels.tsx` is over 7k lines.
- `admin/src/routes/Analytics.tsx` is close to 3k lines.
- `admin/src/routes/Accounts.tsx` is over 1k lines.
- shadcn `Dialog` and `Sheet` primitives exist, but these routes do not use them
  directly today.

## Product Direction

The app should present itself as a support system, not a setup console.

The channel model should support many providers over time. Initial priority:

- Email.
- Web add-on or embedded chat.
- Discord.
- Slack.

Tickets remain the central operating object. New inbound messages create or
update tickets. Tickets need status, assignee, channel, customer/account context,
AI preparation, and answer/reply flows. Automation and runbooks can prepare or
complete the same workflow, with human approval when configured.

## Design Principles

- Default screens answer the primary user question first.
- Diagnostics stay available, but behind sheets or advanced tabs.
- Bounded mutation flows use dialogs so users know what they are changing.
- Inspection flows use sheets so users keep route context.
- Raw payloads, proof evidence, and launch/debug controls are not default page
  content.
- Avoid new domain concepts while clarifying labels. Automations, runbooks, and
  customer identification should be presented as one AI operating system, not as
  competing product areas.

## Channel Setup

### Current Problem

Channel setup tries to be onboarding, provider configuration, launch readiness,
delivery history, queue setup, CRM setup, and webhook diagnostics at the same
time. That makes the route feel overwhelming even when the underlying capability
is useful.

### Target Surface

The default Channel setup page becomes a provider readiness overview:

- Provider cards with status, last sync, blocker count, and next best action.
- Top-level actions for adding a provider and running checks.
- Compact sections for active channels and routing queues.
- CRM connector summary only, not full connector setup inline.

### Dialogs

Use `Dialog` for bounded tasks:

- Add provider wizard.
- Edit provider settings.
- Run advanced checks.
- Export launch proof.
- Create or edit queue.
- Create or edit CRM connector.

The add provider dialog should guide users through provider type, credentials or
connection method, routing target, first test, and completion state.

### Sheets

Use `Sheet` for detail and evidence:

- Provider launch details.
- Sync history.
- Delivery history.
- Webhook inbox.
- Raw config.
- Secret template.
- Adapter matrix.
- CRM connector details.
- CRM webhook inbox.

The sheet title should name the exact provider or connector being inspected.
The sheet body can expose the existing evidence tables and raw technical detail.

### Route Boundary

Channel setup remains the entry point for provider readiness. It should not
become the full CRM admin route. CRM details can stay accessible from Channel
setup for now, but the default route should not show CRM internals unless the
user opens a dialog or sheet.

## Accounts

### Current Problem

Account detail mixes a customer cockpit with editing workflows and CRM
diagnostics. Users need a fast answer to "what is the state of this customer?"
before they need raw records or sync evidence.

### Target Surface

The account detail page becomes an account cockpit:

- Health rollup.
- Account summary.
- Next best action.
- Contacts.
- Recent tickets.
- Active risks and feature requests.

`Prepare action` remains visible because it is a primary workflow.

### Dialogs

Use `Dialog` for account mutation:

- Add insight.
- Edit insight.
- Prepare or approve an account action when extra fields are required.
- Confirm or run CRM sync.

The add insight dialog should capture type, severity, title, body, and optional
source ticket or contact. Risk, feature request, and summary variants should be
handled by the same dialog instead of separate inline editors.

### Sheets

Use `Sheet` for account inspection:

- CRM details.
- External records.
- CRM sync history.
- Raw CRM payloads.
- Ticket preview when staying on the account route is useful.

Insight cards can keep inline acknowledge or resolve actions because those are
small row-level state transitions.

## Analytics

### Current Problem

Analytics mixes an executive dashboard, launch checklist, operational console,
and debug screen. The default page does not make the main decision path obvious.

### Target Surface

The default Analytics page becomes a decision dashboard with three bands:

- Launch readiness.
- Support workload.
- SLA and customer outcomes.

Add top-level tabs or a segmented control:

- Overview.
- Channels.
- Accounts.
- AI/Ops.
- Raw.

### Sheets

Use `Sheet` for detailed analytical inspection:

- Launch proof evidence.
- Channel remediation rows.
- SLA breakdown.
- Assignee, queue, or channel drilldown.
- Schema health detail.

`Launch proof` should include evidence, export, run proof, and provider state.
`Channel remediation` should show actionable rows and link back to Channel setup.

### Raw Metrics

Raw counters and dense metric grids move to the `Raw` tab. They remain available
for debugging and operator trust, but they do not dominate the default view.

CSV export remains a top-level action.

## Automation, Runbooks, And Customer Identification

The user-facing information architecture should not force customers to learn
the internal distinction between automations, runbooks, and customer
identification before they can operate support.

Recommended product grouping:

- `AI setup` or `Automation` as the customer-facing area.
- Runbooks as the configured procedures inside that area.
- Customer identification as the identity resolution step inside the same AI
  setup flow.
- Automations as triggers and approvals around runbooks.

This keeps the strongest existing implementation concepts while reducing product
taxonomy confusion.

## Non-Goals

- No channel provider implementation in this slice.
- No ticket data model rewrite in this slice.
- No Slack, Discord, email, or web add-on backend changes in this slice.
- No full route split unless the implementation plan finds a route is too large
  to refactor safely.
- No visual redesign beyond layout, hierarchy, and shadcn progressive disclosure.

## Implementation Boundaries

The first implementation plan should refactor only the admin UI surfaces:

- `admin/src/routes/Channels.tsx`
- `admin/src/routes/Accounts.tsx`
- `admin/src/routes/Analytics.tsx`

Shared helper components may be extracted if they reduce route size and keep
the new interaction model clear. The implementation should preserve existing
data fetching, mutations, and API contracts unless a small adapter is needed to
move existing content into a dialog or sheet.

## Error Handling

- Dialog mutations should keep inline validation and server error states.
- Sheets should show loading, empty, and failed states without blocking the
  parent route.
- Running checks, exports, and syncs should expose pending, success, and failure
  states in the dialog that launched them.
- Provider and account detail sheets should keep enough context in their title
  and description that users know which object they are inspecting.

## Verification

After implementation:

- Run backend Ruff and pytest.
- Run frontend TypeScript and ESLint.
- Use DOM-based browser verification only. Do not use screenshots or vision.
- Verify Channel setup default route has fewer visible sections and fewer
  immediate actions while preserving provider setup access.
- Verify Accounts default detail reads as a customer cockpit and still allows
  adding insights and inspecting CRM details.
- Verify Analytics default route shows the three decision bands and moves raw
  metrics behind a tab or sheet.

## Open Decisions

All decisions needed for the design are resolved:

- Use progressive disclosure instead of a full route split as the first step.
- Use `Dialog` for bounded tasks.
- Use `Sheet` for inspection and evidence.
- Keep existing capabilities available.
- Keep initial channel priority at email, web add-on, Discord, and Slack.
