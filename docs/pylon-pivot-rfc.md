# Email-First Support System RFC

## Decision

Build an owned Pylon-like product. Do not reduce this repo to a vendor integration.

Initial wedge: email-first B2B support inbox where Outlook and Gmail are channel surfaces, and the admin app is the support system of record.

## Product Spine

Current product shape is email analysis plus draft reply. Target shape is support lifecycle:

```text
Channel adapters
  Outlook / Gmail / Slack / Teams / Discord / Telegram / WhatsApp / Messenger / SMS / web chat
        -> normalized messages
        -> issue + account resolver
        -> AI triage / runbook / assistant
        -> human workspace
        -> actions, replies, knowledge, analytics
```

## MVP Vertical Slice

1. Customer email arrives through Outlook, Gmail, or `/api/process`.
2. System creates or updates a support issue.
3. AI identifies account/contact from existing identity result.
4. AI classifies runbook, priority, and required human review.
5. Admin Inbox shows the issue queue.
6. Issue detail shows timeline, AI summary, runbook, draft reply, and action log.
7. Add-in opens or creates the same issue for the current email.
8. Feedback and evals remain tied to runbooks.

## Data Model

Implemented first:

- `support_issues`: read model over existing `chats`
- `support_queues`: team queues for ticket ownership before an individual assignee claims work
- `support_accounts`: account read model from identity results
- `support_contacts`: contact read model from identity results
- `support_messages`: normalized issue timeline from chat messages
- `support_outbound_messages`: durable web-inbox reply drafts, queued replies, and SMTP delivery state
- `support_delivery_runs`: outbound reply delivery run history
- `support_ai_runs`: issue-linked AI audit records plus durable ticket agent Q/A turns
- `support_action_executions`: issue-linked runbook action execution records
- `support_automation_rules`: workflow rules with trigger, conditions, and actions
- `support_automation_runs`: automation execution history per issue/rule
- `support_issue_events`: append-only issue activity and status-transition audit trail
- `support_notifications`: agent-facing unread/read notifications for assignment and SLA ownership signals
- `support_channels`: normalized channel registry
- `support_channel_cursors`: durable inbound adapter cursor state
- `support_channel_sync_runs`: scheduler/admin sync run history
- `support_channel_webhook_events`: channel webhook inbox for delivery receipts and push channel events
- `support_web_chat_sessions`: public web chat sessions linked to Inbox issues
- `support_issue_assignments`: assignee history
- `support_internal_notes`: internal collaboration notes
- `support_sla_policies`: project-level first-response and resolution targets
- `support_sla_events`: first-response and resolution clocks
- `support_issue_watchers`: ticket follow/mention subscribers
- `support_inbox_views`: saved Inbox filter/view presets for private or shared triage workflows
- `support_reply_macros`: shared/private canned replies for repeated support responses
- `support_customer_portal_sessions`: tokenized customer-facing issue access
- `support_csat_feedback`: customer satisfaction ratings/comments from portal sessions
- `knowledge_articles`: support knowledge base
- `support_knowledge_gaps`: missing-knowledge signals from unresolved issues
- `support_account_insights`: account summaries, risk signals, and feature requests
- `support_crm_connectors`: active CRM connector configuration for account/contact sync
- `support_crm_cursors`: durable CRM polling cursor state
- `support_crm_sync_runs`: CRM connector sync history
- `support_crm_webhook_events`: CRM webhook inbox/events for push sync
- `support_external_objects`: external CRM/account/contact records seen in identity results
- `support_external_sync_runs`: external-object sync observation history
- `chats`: compatibility/cache layer for processed email transcript
- `monitor_runs`: AI/action execution history
- `project_intents`: runbooks, kept under existing table name for compatibility

Next domain hardening:

- channel-specific inbound delivery cursors. Started with adapter-scoped cursor keys such as `inbound:buffer` and `inbound:imap:{host}:{account}:{mailbox}`, with fallback migration from the legacy `inbound` cursor. Admin Channels now exposes the current durable cursor records per channel, including checkpoint key, value, status, and last error.
- channel webhook signature keys per provider. Started with per-channel generic webhook HMAC verification via channel `config.signatureSecretEnv`, plus provider-specific aliases such as `slackSigningSecretEnv`, `teamsSigningSecretEnv`, `discordSigningSecretEnv`, `telegramSigningSecretEnv`, `whatsappSigningSecretEnv`, and `messengerSigningSecretEnv`, resolved from project/tenant secrets first and process env as fallback. SMS/Twilio now uses Twilio-native `X-Twilio-Signature` verification with the configured Auth Token for direct provider calls, while retaining app-token/generic-HMAC fallback for bridges.

## `support_issues`

Fields:

- Tenant/project scope
- Optional `chat` relation
- `source_email_id`
- `channel`, `source`
- `status`, `priority`, `assignee_email`
- `queue_key`, `queue_name`
- `tags`: issue labels for cross-cutting triage, saved as a normalized string list
- `account_name`, `account_domain`
- `contact_email`, `contact_name`
- `subject`, `from_address`
- `ai_summary`
- `activated_intent`
- `requires_human`
- `message_count`
- `action_log`
- `metadata`: ticket attributes, including project-defined `customFields`
- `latest_message_at`

Status values:

- `open`
- `ongoing`
- `done`

Workflow invariant:

- `open` may be unassigned while it waits in triage only when no channel, queue, project default owner, or signed-in manual creator is available.
- Every new ticket gets a queue. Default is `support` / `Support` unless channel or project metadata overrides it.
- `ongoing` and `done` require `assignee_email`.
- If a channel config, matched support queue, or project support settings define `defaultAssigneeEmail`, new tickets are assigned during ingestion and an assignment history row is recorded with `assignedBy=routing`. Precedence is channel owner, queue owner, then project owner.
- Human draft/queued replies auto-claim unassigned tickets to the author.
- Manual tickets created from the admin Inbox default to the signed-in editor as assignee when no explicit assignee is selected.
- Tickets split from an existing thread keep the source owner, or default to the splitting editor when the source ticket was unassigned.
- Queued replies move the ticket to `ongoing`.

Legacy read/write aliases are accepted for compatibility:

- `pending` and `triaged` -> `ongoing`
- `closed` -> `done`

Priority values:

- `low`
- `normal`
- `high`
- `urgent`

## Queues

Admin Channels owns queue setup for now:

- List active and archived support queues.
- Create/update queues with `queueKey`, `name`, optional description, and optional default assignee.
- Archive/restore saved queues.
- Inbox and channel defaults use the same `queueKey`/`queueName` pair.

## Navigation

Immediate:

- Inbox
- Accounts
- Knowledge
- Channels
- Automations
- Analytics
- Monitor
- Support setup
- Customer identity
- Runbooks
- Preview & Publish
- Evaluation
- Settings

Target:

- Inbox
- Accounts
- Knowledge
- Runbooks
- Automations
- Analytics
- Channels
- Settings

Navigation now uses product routes for support setup: `/support-setup`, `/customer-identity`, and `/runbooks`. The old `/pipeline`, `/customer`, and `/intents` paths redirect for compatibility because the backend collection and API contract still use legacy names such as `project_intents`.

## Phase Plan

Phase 1: issue spine

- Add `support_issues` schema and migration.
- Sync `/api/process` into issue read model.
- Add admin issue API.
- Add admin Inbox route. Started with ticket list/detail plus full Board mode and compact Kanban lanes: Open, Ongoing, Done, including drag/drop status moves.
- Add add-in “Open/create issue” flow. The Outlook add-in and Gmail add-on also surface the same next-action decision for the current email's ticket: claim, queue approval, review/send approval, retry failed delivery, close, or open the full issue.

Phase 2: normalized messages and assignments

- Split message timeline out of `chats`. Started with `support_messages`.
- Add durable outbound reply records. Started with `support_outbound_messages`.
- Add channel delivery for web-inbox replies. Started with SMTP delivery for email replies, `support_delivery_runs`, admin delivery run, internal cron endpoint, and optional in-process scheduler.
- Add channel-aware outbound adapter hook. Started with generic configured provider webhook delivery for non-email channels, native bot delivery for known providers, and provider-specific reply target metadata for draft/queued replies before delivery.
- Add delivery failure recovery. Started with failed-delivery issue summaries, Inbox `Failed delivery` filter/badges, bulk retry for selected failed tickets, explicit admin/internal delivery-run retry of failed replies, and transient provider backoff for 408/425/429/5xx responses.
- Add customer-facing issue portal. Started with tokenized `support_customer_portal_sessions`, admin link creation, public issue view, and customer message append.
- Promote identity results into account/contact read models. Started with `support_accounts` and `support_contacts`.
- Add assignee/user relation. Started with `support_issue_assignments`, member picker/assign-to-me controls, and assignment-change events.
- Add owner notifications. Started with `support_notifications`, unread Inbox notification rail, assignment notifications, and assigned-ticket SLA breach notifications.
- Add internal notes. Started with `support_internal_notes` and Inbox collaboration notes.
- Add watchers and mentions. Started with `support_issue_watchers`, watch/unwatch controls, and `@agent@example.com` internal-note mention notifications.
- Add status transition events. Started with `support_issue_events`.

Phase 3: account intelligence

- Promote identity result into `accounts` and `contacts`. Started with `support_accounts` and `support_contacts`.
- Add account issue history. Started with account detail issue timeline.
- Add feature request/risk summaries. Started with `support_account_insights`.
- Account intelligence now extracts risk and feature-demand signals from ticket subject, intent, and customer-message text, stores matched keywords/evidence on `support_account_insights`, and keeps the account health rollup tied to actual support language instead of only CRM/manual notes.
- Normalize external CRM records. Started with `support_external_objects`, `support_external_sync_runs`, and account detail external records.
- Add active CRM connector jobs. Started with `support_crm_connectors`, `support_crm_cursors`, `support_crm_sync_runs`, admin CRM sync, internal cron endpoint, optional in-process scheduler, deterministic buffer adapter, generic HTTPS polling, HubSpot private-app polling, and Salesforce REST polling for companies/accounts and contacts.
- Add CRM push sync. Started with `support_crm_webhook_events`, token-guarded internal ingest, idempotent event processing, admin webhook inbox, and analytics counters.
- Operate account health. Started with an Admin Accounts operations panel that rolls up at-risk accounts, needs-attention accounts, CRM sync attention, feature demand, and the top next account action before operators drill into a single customer.
- Add CRM launch recovery. Started with project launch-proof warning remediation that re-runs active CRM connector syncs when account intelligence has CRM/external sync failures, records the action in proof history, and routes operators back to Admin Channels for connector evidence.
- Add CSAT recovery loop. Started with low-CSAT launch-proof remediation that reopens/assigns/raises affected tickets, tags them for follow-up, adds an internal recovery note, and writes an account-risk insight when the ticket is linked to an account.

Phase 4: knowledge and channels

- Add searchable KB articles. Started with `knowledge_articles`, including article source URL/provenance and public/internal/private visibility metadata.
- Add public help center. Started with read-only published-article JSON and HTML endpoints for customer-facing article discovery; internal/private articles are excluded even when published.
- Detect missing knowledge from unresolved issues. Started with `support_knowledge_gaps`, in-ticket knowledge suggestions, and ticket agent answer citations.
- Close the knowledge feedback loop. Started with machine-readable launch-proof warnings plus a draft-only proof action that turns open knowledge gaps into KB article drafts, resolves the source gaps, and links the proof run to the created article so a human can edit/publish it.
- Operate the knowledge surface. Started with an Admin Knowledge operations panel that exposes the public help-center URL, articles API URL, public/internal/source-linked/gap counts, recent article revisions, and the next highest-severity gap action without forcing operators to decode article lists.
- Seed empty knowledge bases. Started with launch-proof `knowledge_base_starter`, which creates an internal draft support-response standards article when the project has no KB content, leaving publication to a human.
- Add inbound channel cursor loop. Started with `support_channel_cursors`, `support_channel_sync_runs`, admin channel sync, internal cron endpoint, optional in-process scheduler, buffer adapter, and IMAP adapter.
- Add channel webhook inbox. Started with `support_channel_webhook_events`, token-guarded internal ingest, outbound delivery receipt matching, admin webhook inbox, analytics counters, and ticket-detail provider event evidence for the channel events that created, updated, or delivered replies on that ticket.
- Add Slack/Teams/web chat adapters. Started with public web chat sessions, customer message append, Inbox issue creation, admin channel session history, Slack Events API issue ingest, Teams activity issue ingest, first-class Discord/Telegram/WhatsApp/Messenger/SMS provider endpoints, and generic channel webhook message ingest. Web chat keeps ticket-per-message semantics while returning a session-level transcript across all linked ticket IDs, so visitors still see the whole conversation after each new message opens a new ticket. The hosted chat shows the latest opened ticket plus session ticket/message counts, and Admin Channels shows the same session evidence with linked ticket IDs, latest ticket, and transcript message count so operators can verify channel-surface continuity against the support system of record.
- Add channel setup UX. Started with admin channel setup metadata: inbound webhook URL, provider webhook URL, token/signature env names, outbound config keys, payload examples, provider presets, and first-class Email/Slack/Teams/Discord/Telegram/WhatsApp/Messenger/SMS/Webhook channel choices. Presets now expose support defaults directly: new message equals new ticket, autopilot prep covers triage/custom fields/approval draft, and human review stays on. Channels now expose a launch playbook that turns setup/launch proof state into operator actions for copying provider URLs/config, installing Slack/Telegram/web chat/bridge adapters, fixing ticket defaults, validating setup, and running proof steps.
- Add channel surface next action. Started with a Channels rail that points operators at the first blocked surface and lets them apply a preset, open setup, fix ticket mode/autopilot config, validate provider credentials, or run launch proof without hunting through raw channel config.

Phase 5: support KPIs

- First response time. Started with support analytics average first response minutes.
- Time to resolution. Started with support analytics average resolution hours.
- SLA breach tracking. Started with overdue SLA event count, due-soon SLA readiness warnings, project-level `support_sla_policies`, admin/internal SLA breach scan, `sla_breached` automation trigger, and launch-proof `sla_due_soon_watch` remediation for pre-breach ownership.
- Support workload. Started with active-ticket workload by queue, assignee, and channel, plus Analytics links back into filtered Inbox views.
- Response queue. Started with normalized timeline-derived Needs response counts, oldest customer-wait hours, and Analytics links back into the filtered Inbox.
- Support health insights. Started with Analytics cards that translate SLA risk, first-response speed, resolution speed, owner workload, and CSAT into operator-facing severity, detail text, and filtered Inbox links.
- Runbook automation rate. Started with `support_automation_rules`, `support_automation_runs`, admin Automations, one-click human-in-loop autopilot/SLA recipes, and analytics counters. Automations now also expose an operations panel for active-rule count, approval-agent coverage, auto-send policy, failed-run recovery, and the next human-in-loop action.

Due-soon SLA warnings are treated as pre-breach work, not static metrics. Project launch proof can run `sla_due_soon_watch` from Analytics to assign and move affected tickets into `ongoing`, raise priority, tag them with `sla-due-soon-watch`, add an internal note with the target/event type, and create an account-risk insight for linked accounts.

## Ticket Workspace

The product UI uses ticket language even though the compatibility collection remains `support_issues`.

Workflow lanes:

- `open`: new ticket, needs first human/agent pass.
- `ongoing`: work started, reply/action in progress, or customer waiting.
- `done`: closed/resolved.

Assignment rule: every launchable ticket needs an assignee. `open` tickets can temporarily sit unassigned during triage, but launch readiness blocks until they are claimed or routed. Moving to `ongoing` or `done`, queueing a reply, or sending a reply requires/sets an owner. Human replies claim unassigned tickets for the current editor; automation replies use explicit owner metadata first, then queue/channel/default routing including least-open queue owners, before falling back to the automation user. In the admin Inbox, moving an unassigned ticket into `ongoing` or `done` auto-claims it for the current user when available; otherwise the move is blocked until an assignee is set.

Inbox views:

- List/detail: triage queue plus selected ticket workspace.
- Board: full Kanban board with Open, Ongoing, and Done lanes. Cards show priority, assignee, account/contact, channel, runbook intent, and support drag/drop status moves. Dropping an unassigned ticket into Ongoing or Done claims it for the current user. Board and List expose the same status/queue/account/channel/assignee/label filters, including reply/action approval queues. The board detail panel now supports account intelligence, contact context, a unified review package, automation audit, activity, ticket workflow edits, labels, watcher follow/unfollow, portal link creation, SLA visibility, and internal notes without switching to List. Inbox defaults to Board; List remains explicit via `?view=list`.
- Manual create: agents can create an email-replyable Inbox ticket from a customer message inside the admin app, with priority and assignee set up front. Splitting a message into a new ticket also keeps ownership launch-safe by carrying the source owner or assigning the splitting editor.
- Bulk triage: list and board views support multi-select claim for currently unassigned tickets and Open/Ongoing/Done moves through the same issue update path, preserving assignment history, status events, and automations without overwriting existing owners.
- Notifications: unread assignment, customer-reply, and SLA-breach notifications appear in the Inbox sidebar for the signed-in agent. Opening a notification jumps to the linked ticket and marks the notification read. Self-assignments and self-sent customer-message events are not notified.
- Watchers: agents can follow/unfollow a ticket from the sidebar. Customer replies and internal notes notify active watchers, and `@email` mentions auto-add the mentioned agent as a watcher plus send a direct mention notification.
- Labels: agents can add/remove issue labels from the Lifecycle panel, search/filter by labels in the Inbox, and use labels in automation conditions.
- Needs response: list and board views expose customer-last-message tickets with a badge and `filter=needs-response`, derived from normalized timeline direction so email, Slack, Teams, Discord, Telegram, WhatsApp, Messenger, SMS, and web chat use the same operator queue.
- Saved views: agents can save current Inbox search/status/queue/account/channel/assignee/label/view-mode filters as private or shared views, apply them from the Inbox rail, overwrite/rename owned views with the current filters, and delete owned views. The same filters are URL-backed so account pages and shared links can open the exact support queue.
- Support views: Inbox ships built-in global presets for Needs response, Approvals, Needs assignee, Overdue SLA, SLA due soon, Failed delivery, and Low CSAT. These reset stale account/channel/search scope, choose Board or List intentionally, and keep the Pylon-style operator queues visible even before a team creates saved views.
- Queue owners: queue metadata can define `allowedAssigneeEmails`. Admin Channels exposes the owner list, Inbox assignee pickers honor it, and backend issue create/update rejects assigning a ticket to someone outside the selected queue owners.
- Queue transfer routing: moving a ticket into a queue with static or least-open routing auto-claims unassigned tickets for the selected queue owner, and reassigns tickets whose previous owner is not allowed on the destination queue.
- Queue owner capacity: least-open queue metadata can define `ownerCapacity`. Routing skips owners at or above that active-ticket count, leaves tickets unassigned when every eligible owner is full, and Analytics reports capacity warnings, health insight cards, and owner/queue capacity rows. Inbox queue and assignee controls can request queue-owner workload metadata and label owners with active/capacity counts before a human override; backend assignment updates also record `assignment_capacity_override` events when a manual assignment exceeds capacity.
- Custom fields: Project Settings defines typed ticket custom fields in `support_sla_policies.metadata.customFields`. Inbox detail renders those attributes for each ticket, issue search includes field keys/values, and issue updates store normalized values in `support_issues.metadata.customFields` with an audit event when values change. The ticket agent can now prepare missing field values from ticket messages as a pending `set_custom_fields` action, so humans approve structured metadata before it changes the ticket.
- Support settings readiness: Project Settings now exposes a support operations panel with SLA clocks, default queue/owner routing, custom-field coverage, business-hours status, one-click baseline defaults, Analytics navigation, and SLA scan execution so launch-critical ticket defaults are visible before operators scroll through raw settings.
- Schema readiness: Analytics shows support collection, critical field, and migration-file health so a deploy cannot look ready while old PocketBase data is missing field-only migrations like issue labels, custom-field metadata, merge fields, or email thread metadata. Launch readiness now blocks on missing support collections, missing critical fields, or missing support migration files; when collections are absent, Analytics still returns a safe zero-metric summary with schema blockers instead of crashing before the operator sees the rollout problem.

Compatibility aliases:

- `pending` and `triaged` normalize to `ongoing`.
- `closed` normalizes to `done`.

Ticket detail now includes:

- normalized message timeline
- channel source proof panel with provider, channel key, ticket creation mode, resolver action, source message/ticket ids, external ticket/message keys, and reply target metadata so agents can verify which channel event created the ticket and where replies route
- inbound message attachments surfaced in the ticket timeline with filename, type/size metadata, and links when the channel provides URLs; email/add-in ingestion preserves original customer attachment metadata on the customer timeline message without copying raw base64 into `support_messages`, and Slack/Teams/Discord/Telegram/generic channel webhook ingestion normalizes provider attachment metadata into the same timeline field. Slack and Teams attachment-only inbound messages create tickets with attachment-derived bodies instead of being dropped as empty text.
- channel-aware reply composer that stores `metadata.replyTarget` plus channel/thread/conversation/chat ids on drafts before approval, so Slack/Teams/Discord/Telegram/WhatsApp/Messenger/SMS/web-chat replies do not depend on an email recipient
- shared/private reply macros that agents can insert into the reply composer or save from a good draft; macros can render ticket-aware placeholders such as contact/account/ticket/custom-field values before insertion
- manual reply approval toggle for save/queue flows
- unified review package at the top of each ticket when AI/human-loop work is pending. It puts approval-ready reply drafts and action proposals beside the timeline/knowledge/agent workspace, with approve, approve-and-send, request-changes, approve-action, and reject-action controls in one place. The broader approval workspace is still surfaced through Inbox Approvals filter, card/list badges, and the review queue; the queue now shows compact next-review cards with customer, assignee, package contents, and prepared-work preview so reviewers can scan before opening a ticket. Bulk action rejection prompts for an optional reviewer note, and Action history cards show approved/rejected state, reviewer, timestamp, and note so rejected agent work stays explainable in the audit trail.
- actionable knowledge suggestions and in-ticket knowledge search from `knowledge_articles` that can be inserted into the reply composer or used to ask the agent for a cited draft
- issue-specific knowledge gaps with one-click draft article creation back to the knowledge base, plus ticket-side publishing for reviewed draft articles and revision audit metadata on create/update/publish
- article provenance fields so support agents can keep source URLs with KB entries while deciding whether each published article is public, internal, or private
- Ask agent panel with durable ticket chat history that prepares a draft reply or requests guarded `Queue if safe` auto-send, stores citation previews with source URL and public/internal/private visibility on the AI run/reply/event, cites relevant articles after reload, uses account health/open-signal/CRM context plus prior agent Q/A as follow-up context, creates an issue-specific knowledge gap for no-source, low-confidence, or errored answers, and lets prior agent answers be reused as replies
- Next-action card in the ticket workspace that tells the editor whether to assign ownership, review reply/action approvals, respond, recover failed delivery, watch SLA/delivery, or close the ticket, with direct controls for assignment, package review, reply prep, retry, delivery run, SLA watch/escalation, and close
- Agent field preparation that extracts configured custom ticket fields from customer messages, records a `field_extraction` AI run, and creates an approval-ready action proposal
- Autopilot proof panel that reads `channel_agent_autopilot` issue events and shows whether channel automation prepared triage, custom fields, and an approval draft, including execution/run/reply ids plus incomplete-package gaps
- editable approval drafts from agent/autopilot answers; editing an already-approved draft or a draft with requested changes resets it to pending approval
- in-ticket account intelligence with account health, open risks, feature requests, CRM providers, CRM record count, latest sync, account-level signals, and one-click signal resolution from the ticket workspace
- project-defined custom ticket fields for structured attributes like plan, severity reason, ARR, region, or renewal date
- assignee member picker, Needs assignee filter/badges, one-click claim from queue cards, notes, SLA, portal, activity, runbook/action, AI-run, and contact side panels
- watcher list with follow/unfollow, note watcher notifications, and direct internal-note mentions

Human-in-the-loop flow:

1. Agent prepares an answer with `POST /api/admin/projects/{project_id}/issues/{issue_id}/agent-answer`.
2. Backend scores relevant KB articles and builds an answer from ticket context.
3. Backend stores the agent Q/A turn in `support_ai_runs` with `source=agent_answer`.
4. Backend stores a draft outbound reply with `metadata.approvalRequired=true`.
5. Human either approves with `POST /api/admin/projects/{project_id}/issues/{issue_id}/replies/{reply_id}/approve` or requests changes with `POST /api/admin/projects/{project_id}/issues/{issue_id}/replies/{reply_id}/changes`.
6. Backend preflights queue owner rules before marking a reply approved, then records `metadata.reviewStatus=approved` plus `approvedBy`/`approvedAt`, or `metadata.reviewStatus=changes_requested` plus reviewer note fields and a `reply_changes_requested` activity event. Bulk approval keeps per-ticket failures in the response instead of approving later tickets silently after an ownership rejection.
7. Human edits the approval draft in place if needed; editing an approved or changes-requested draft moves it back to pending review.
8. Backend rejects delivery for approval-required replies until `metadata.approved=true`.

## Generic Channel Webhooks

`POST /api/internal/support/channel-webhooks/{channel_key}` now accepts both delivery receipts and inbound message events.

Ticket creation policy is per channel:

- Default: `per_message`, matching the product rule that a new channel message opens its own ticket.
- `config.ticketCreationMode = "per_message"`: every inbound message creates or resolves to its own ticket, even when the provider sends `threadId` / `conversationId`.
- `config.ticketCreationMode = "per_thread"`: messages with the same provider thread/conversation update the same ticket.
- Email add-in, Gmail add-on, IMAP, and buffer email channels pass provider thread metadata when available. With `ticketCreationMode=per_thread`, their ticket source key becomes `email-thread:{source}:{threadId}` while timeline messages keep the concrete provider message id for duplicate detection and add-in/Gmail ticket lookup.

Channel-level autopilot config can prepare the human-review package without requiring a separate automation rule:

- `config.autoPrepareAgentReply = true`: prepare triage, configured custom fields, and a knowledge-cited approval draft when a channel-created ticket is opened.
- `config.autoPrepareAgentReplyOnUpdate = true`: prepare the same follow-up package when an existing channel ticket receives another customer message.
- `config.agentAutoSend = true`: request guarded auto-send for channel autopilot replies. The backend only queues the reply when approval is not required and the existing confidence/citation guard passes; otherwise it leaves a draft for human approval with `autoSendBlockedReason`.
- `config.defaultAssigneeEmail`: optional channel-level owner for new tickets; overrides project support settings.
- `config.defaultQueueKey` / `config.defaultQueueName`: optional channel-level queue for new tickets; overrides project support settings.
- `support_queues.defaultAssigneeEmail`: optional queue-level owner for new tickets after queue routing; used when the channel does not set a direct owner.
- `config.outboundPayloadMode = "provider"`: send provider-shaped JSON for Slack, Teams, Discord, Telegram, WhatsApp, Messenger, and SMS. Use `"generic"` when an external adapter owns provider formatting.
- `config.includeFeedbackLink = true`: include a customer portal CSAT link in channel autopilot approval drafts before human review/send.
- `config.agentQuestion`: optional prompt for the channel agent response. Defaults to an approval-ready response from ticket context and knowledge. Admin Channels exposes this as Agent instruction so operators can tune channel-specific autopilot behavior without editing raw JSON.

If an automation rule already prepared an agent reply for the same event, channel autopilot skips its own reply draft to avoid duplicates.

Inbound message events need message text in one of:

- `body`
- `text`
- `content`
- `messageText`
- nested `message.text` / `message.content`

Useful fields:

- `eventId` / `event_id`
- `eventType` / `event_type`, for example `message_created`
- `provider`, for example `discord` or `telegram`
- `channelId` / nested `chat.id`
- `threadId` / `conversationId`, optional; absent means one ticket per message
- `messageId`, recommended when `ticketCreationMode` is `per_message`
- `author`, `sender`, `from`, or `user`

Every channel message stores canonical external keys in message metadata, issue events, automation context, and autopilot draft context:

- `externalProvider`: normalized provider, for example `slack`, `teams`, `discord`, `telegram`
- `externalChannelKey`: `{provider}:{channelKey}:{workspaceId}:{channelId}`
- `externalConversationKey`: `{provider}:{channelKey}:{workspaceId}:{channelId}:{conversationId}`
- `externalThreadKey`: `{provider}:{channelKey}:{workspaceId}:{channelId}:{threadId}`
- `externalMessageKey`: `{provider}:{channelKey}:{workspaceId}:{channelId}:{messageId}`
- `externalTicketKey`: equals `externalMessageKey` for `per_message` channels and `externalThreadKey` for `per_thread` channels
- `externalAuthorKey` / `externalAuthorDisplay`: provider-scoped actor identity for routing, reply targeting, and audit

Legacy `source_email_id`, `sourceIssueId`, and `sourceMessageId` stay for compatibility. New channel adapters should use the canonical keys for resolver logic, automation conditions, and reply target metadata.

Every inbound channel message writes a `resolver` proof object into message metadata, issue event metadata, ingestion return values, and channel webhook event results. The proof records `resolverAction` (`created`, `updated`, or `deduplicated`), `ticketCreationMode`, source IDs, canonical external keys, channel key, issue ID, and message ID. Admin Channels shows this proof in the webhook inbox so operators can verify whether an incoming Slack/Teams/Discord/Telegram/WhatsApp/Messenger/SMS/generic event opened a new ticket, appended to an existing ticket, or was skipped as a duplicate. Inbox ticket source proof links back to the selected Admin Channels setup view so operators can move from a ticket to the exact channel configuration and launch proof.

Delivery receipts still use `eventType` plus `providerMessageId` and update `support_outbound_messages`.

## SLA Policy

Project Settings owns the active support SLA policy. New issues copy the current policy values into their pending SLA events:

- `firstResponseMinutes`: target for first human or outbound response.
- `resolutionMinutes`: target for issue closure.
- `metadata.defaultAssigneeEmail`: optional project-level owner for new tickets when the channel does not override it.
- `metadata.defaultQueueKey` / `metadata.defaultQueueName`: optional project-level queue for new tickets when the channel does not override it.
- `metadata.customFields`: optional project-level ticket attribute definitions. Supported field types are `text`, `number`, `select`, `boolean`, `date`, and `url`.
- `businessHours`: optional business-hour calendar for new SLA clocks. When enabled, SLA minutes accrue only inside selected weekly windows.

Business hours shape:

```json
{
  "enabled": true,
  "timezone": "Europe/Zurich",
  "start": "09:00",
  "end": "17:00",
  "days": [0, 1, 2, 3, 4]
}
```

Existing issue clocks are not rewritten when the policy changes.

## Customer Portal

Agents can create a portal link from an issue. The stored session keeps only a token hash and links to one issue. The public portal exposes customer/agent messages only; internal notes and AI drafts stay private. The portal also lets customers search public knowledge articles scoped to the same project before replying or leaving CSAT.

Inbox replies and prepared agent drafts can also include a CSAT link. When `includeFeedbackLink` is true, the backend creates a fresh portal session before storing the outbound reply and appends `Rate this support experience: <portal-url>` to the reply body. `SUPPORT_PUBLIC_BASE_URL` controls the public URL base; `APP_BASE_URL` is the fallback.

Public endpoints:

- `GET /support/portal/{token}`: basic customer-facing issue page.
- `GET /api/support/portal/{token}`: JSON issue view.
- `POST /api/support/portal/{token}/messages`: append a customer message and reopen a done issue.
- `POST /api/support/portal/{token}/feedback`: save or update one CSAT rating/comment for the portal session.

CSAT feedback is visible on the issue side panel, summarized on Inbox ticket rows/cards, filterable via `filter=low-csat`, and rolled into Analytics as response count, average rating, low-rating count, and a launch-readiness warning when ratings are 1-2.
Live low CSAT is now actionable immediately: ratings of 1-2 tag the ticket with `low-csat`, raise normal/low priority tickets to high, reopen done tickets into `ongoing` when already assigned or `open` when unassigned, and trigger `issue_updated` automations with `source="customer_portal"` plus rating/comment context so recovery rules can prepare the next human-reviewed reply.

## Automations

Admin Automations stores project-scoped workflow rules. Supported triggers:

- `issue_created`
- `issue_updated`
- `sla_breached`
- `any_issue_event`
- `manual`

Condition examples:

```json
{
  "priorityIn": ["high", "urgent"],
  "tagsAny": ["vip", "billing"],
  "customFields": {"plan": "Enterprise"},
  "customFieldExists": ["seats"],
  "unassigned": true,
  "requiresHuman": true
}
```

Supported action types:

- `assign`: set `assigneeEmail`
- `set_status`: set issue status
- `set_priority`: set issue priority
- `set_custom_fields`: merge typed values into `support_issues.metadata.customFields`
- `prepare_custom_fields`: ask the ticket agent to extract missing configured custom fields and create a pending approval action by default
- `add_note`: append internal note
- `queue_reply`: create queued outbound reply; approval is required by default for automation-created replies unless the action explicitly sets `approvalRequired=false`. Optional `assigneeEmail` / `ownerEmail` / `reviewerEmail` sets the ticket owner/reviewer for the queued reply. Optional `includeFeedbackLink=true` appends the same CSAT portal link used by manual Inbox replies.
- `prepare_agent_reply`: prepare a knowledge-cited approval draft via the ticket agent. Optional `includeFeedbackLink=true` includes the same customer portal CSAT link in the generated draft. Optional `autoSend=true` uses the same confidence/citation guard as channel autopilot before queueing without review. No-source, low-confidence, or errored agent answers automatically upsert an issue-specific knowledge gap linked to the AI run.
- `record_action`: append action execution audit row

`prepare_agent_reply` supports:

```json
{
  "type": "prepare_agent_reply",
  "question": "Draft an approval-ready response from the ticket context and knowledge base.",
  "createDraft": true
}
```

Admin Automations includes an Autopilot recipe that creates an active `issue_created` rule for unassigned human-review tickets. It assigns the ticket to the current user/member, prepares triage changes, proposes configured custom fields, and prepares a knowledge-cited approval draft. It also includes an SLA breach recipe that assigns, raises priority, records an internal note, and prepares an urgent customer update. The structured action builder exposes the same CSAT link toggle for queued replies and agent drafts, so operators do not need raw JSON edits for feedback-enabled automation.
Automation preview now returns a safety summary before operators run a rule or backlog: matched action count, approval work, direct ticket mutations, customer reply creation, auto-send, blocked auto-send, and warnings for ungated customer/ticket changes.
Automation-created queued replies and agent drafts store `metadata.automationContext` with rule/channel, trigger, action, source message, and actor provenance; Inbox approval cards render this as Autopilot context before humans approve or request changes.
`record_action` can also create a pending non-reply action proposal with `approvalRequired=true` and a `proposedAction`. Supported approval executors are `assign`, `set_status`, `set_priority`, `set_custom_fields`, and `add_note`; unsupported external tool proposals are approved as audit records without pretending the tool ran. Inbox Action history renders these pending proposals with Approve/Reject controls, counts them in the Approvals lane, and keeps review outcome/reviewer/note visible after approval or rejection.
Analytics counts both pending approval reply drafts and pending action proposals in `issuesNeedingApproval`, and the launch warning label treats them as one human-review queue.
`prepare_custom_fields` uses colocated prompt files under `backend/automail/support/prompts/`, validates extracted values against the project custom-field schema, records a `field_extraction` AI run, and proposes `set_custom_fields` for human approval unless the automation explicitly sets `approvalRequired=false`.
`prepare_agent_reply` also supports policy-driven auto-send with `approvalRequired=false` and `autoSend=true`. This creates an approved queued reply, not a pending draft, so the delivery runner can send it through the normal channel adapter path. Runtime confidence policy still wins over the rule flag: auto-send only proceeds when the draft is high confidence and has at least one knowledge citation. Otherwise the reply stays as a pending approval draft with `autoSendPolicy="confidence_guard"` and `autoSendBlockedReason` such as `confidence_below_threshold` or `missing_citations`. If a rule requests `autoSend=true` while approval is still required, the reply remains a pending approval draft and stores `autoSendBlockedReason="approval_required"`. Inbox reply cards and automation run payloads surface `autoSendRequested`, effective `autoSend`, `autoSendPolicy`, and any blocked reason so human reviewers can audit why an agent draft did or did not send.
No-approval or auto-send agent actions count as agent automation, but they do not satisfy the human-in-loop launch gate. Launch readiness requires an active agent draft action with approval required, plus a successful proof run that produced an approval-required reply.

Reply lifecycle triggers are available for post-human-loop automation:

- `reply_approved`: fired after a reply approval is recorded and the ticket is claimed/moved into Ongoing.
- `reply_sent`: fired after channel delivery succeeds, first-response SLA is marked met, and the default Ongoing move has happened so rules can intentionally move the ticket to Done.
- `reply_failed`: fired after delivery failure notification/audit.
- `reply_deferred`: fired when delivery remains queued for retry.

Existing tickets also trigger `issue_updated` automations when new customer messages arrive through email, customer portal, web chat, Slack, Teams, Discord, Telegram, WhatsApp, Messenger, SMS, or generic channel webhooks. This lets agent rules prepare follow-up drafts on every customer reply, not only on first ticket creation.
Assigned owners and active watchers also receive unread `customer_message` notifications for those follow-up messages, so customer replies surface in the Inbox notification rail instead of relying only on list sorting.

SLA breach processing:

- Admin run: `POST /api/admin/projects/{project_id}/support/sla/run`.
- External cron: `POST /api/internal/support/sla` with `X-Support-Sync-Token: $SUPPORT_SLA_TOKEN` or fallback `$SUPPORT_SYNC_TOKEN`.
- Optional in-process loop: set `SUPPORT_SLA_INTERVAL_SECONDS` to a positive value.
- Optional scheduler scope: `SUPPORT_SLA_TENANT_ID`, `SUPPORT_SLA_PROJECT_ID`, `SUPPORT_SLA_LIMIT`.
- Each pending overdue SLA event is escalated once by adding `metadata.escalatedAt`, recording a `sla_breached` activity event, and running active `sla_breached`/`any_issue_event` automations. The SLA event remains pending until the first-response or resolution milestone is met, so the overdue queue stays accurate.
- Assigned tickets also emit an unread `sla_breached` notification for the current owner unless the owner triggered the escalation.

## Channel Sync

Admin Channels can run inbound sync. The sync loop reads active email channels, loads new messages from the configured adapter, runs the existing project-scoped pipeline, stores the chat transcript, and upserts the support issue.

Admin Channels also has lifecycle smoke. It sends a provider-style inbound message, verifies a ticket is created, queues an approval-required reply, approves it, and delivers it through the normal app reply path. Analytics marks active external channels as blocked until HTTP inbound smoke, outbound smoke, HTTP lifecycle smoke, and attachment-only HTTP lifecycle smoke have passed. Direct smoke remains a local adapter diagnostic; launch proof must exercise the provider endpoint/auth surface. Active email channels are blocked until the latest email sync processed at least one inbound message, recorded the created or linked ticket ID, and the support delivery runner sent at least one email reply without failures. Active web chat channels are blocked until hosted or embedded chat creates a session linked to an Inbox ticket and an Inbox reply is delivered back into that session.

Each external channel setup now exposes Launch proof from the latest smoke runs:

- Inbound smoke: HTTP provider endpoint/auth path creates a ticket.
- Outbound smoke: app reply leaves through the provider adapter.
- Lifecycle smoke: HTTP provider endpoint, ticket creation, approval, and reply delivery all work together.
- Attachment lifecycle smoke: HTTP provider endpoint receives a provider-shaped attachment-only message, creates a ticket, records `attachmentCount` and `fileOnly`, approves a reply, and delivers it.
- Launch proof now requires concrete smoke targets and artifacts: native/provider channels must configure real provider smoke targets such as Slack channel IDs, Teams service URL plus conversation target, Telegram chat ID, WhatsApp recipient, Messenger PSID, or SMS recipient before proof can pass. Inbound and lifecycle checks must record the created ticket ID, and lifecycle checks must also record the approval reply ID. Provider-shaped/native bot outbound checks must record the provider message ID plus sanitized delivery route and provider response proof. Inbound proof for route-addressed providers such as Slack, Teams, Discord, and Telegram records `smokeTarget`, and outbound, lifecycle, and attachment lifecycle artifacts must also match the current configured live smoke target, so stale proof from an old Slack/Teams/etc. target blocks readiness after target config changes. A successful processed run without those targets/artifacts remains blocked because it does not prove the support-system-of-record path or provider acceptance path.
- Channels configured with provider signing secrets must record the expected signature auth mode from the HTTP smoke path, for example `slack_signature` for Slack and `hmac_signature` for bridge/generic HMAC channels. Slack channels also require `slack_signature` proof when default `SUPPORT_SLACK_SIGNING_SECRET` exists, and Telegram channels require `telegram_secret_token` proof when the native Telegram secret token is configured. A token-auth smoke from before an auth change no longer proves launch readiness.
- Channels with replay-protected HMAC configured must also record the timestamp auth artifact from the HTTP smoke path. Inbound and lifecycle smoke stay blocked until the run result includes the configured signature timestamp header, proving `timestamp.raw_body` signing was used.

The Channels surface treats Slack, Teams, Discord, Telegram, and generic Webhook channels as launch-ready only after all required checks pass, with inbound, lifecycle, and attachment-only lifecycle checks recorded through `transport=http`. Email channels use `email_sync_delivery` proof instead of provider smoke: inbound sync must create tickets and outbound delivery must prove replies leave the app. Web chat uses `web_chat_session_delivery` proof instead of provider smoke: the hosted page or embed must create a session with a linked ticket, then an internal `web_chat_internal` reply delivery must prove app replies reach the visitor chat.
Launch proof also exposes a compact blocker list from missing or failed smoke checks, and the Channels surface shows the first concrete blocker in the channel surface grid instead of only saying that launch smoke is missing. Each blocker carries its smoke action and can be rerun directly from the launch proof panel.
Admin Channels now shows the live proof target as an operator checklist before launch proof runs. The checklist names the required provider target, the config key to save, whether the value is real rather than a placeholder, and the latest proof evidence rows for target config, provider validation, inbound smoke, outbound smoke, lifecycle smoke, attachment lifecycle, and channel autopilot prep. Operators can copy a compact launch-proof bundle from the channel setup view with channel identity, blockers, live targets, checklist, playbook, setup readiness, and proof evidence for handoff or release review.
Admin Channels also exports a project-level channel activation plan. The plan combines activation next actions, per-surface ticket/automation defaults, required missing env vars, blank secret template, live smoke target keys, setup commands, and setup package metadata so provider setup can be handed to ops without reading UI state. `GET /api/admin/projects/{project_id}/channels/activation-plan` returns the same handoff artifact for scripts, release checks, and customer onboarding runs that cannot rely on the browser download.
If project-level launch proof cannot be loaded, Admin Channels still treats active email and web chat channels as launch-proof-required instead of hiding those gates. Email fallback proof can show the latest sync artifact and still blocks until that run recorded a ticket ID plus delivery proof exists; web chat fallback shows session and delivery proof as missing until Analytics can provide concrete session/reply evidence.

Analytics also exposes project-level Launch proof. It combines schema readiness with required channel proof, including email lifecycle proof, web chat session/reply delivery proof, ticket-creation readiness, reply-route readiness, channel-autopilot prep readiness, knowledge-assist readiness, account-intelligence readiness, human-loop automation readiness, ticket-workflow readiness, external channel live target config, external channel smoke proof, external attachment-only lifecycle proof, default owner routing, ready channels, blocked channels, configured channel backlog, and the first blocker per channel. The Analytics API, UI, CSV export, downloadable launch-proof JSON bundle, and `launch_gate --bundle-file` artifact also return explicit ticketCreation, replyRoute, channelAutopilot, knowledgeAssist, accountIntelligence, humanLoop, ticketWorkflow, and channelBacklog readiness/context, email sync/delivery, external live-target, external attachment-lifecycle, and web-chat session/delivery counters so launch dashboards and release handoffs can distinguish which channel, knowledge, account, approval-loop, Kanban workflow proof, or paused omnichannel surface is missing. Analytics renders the channel backlog as an actionable ledger that links each paused surface to its Channels setup row, so the launch proof answers both "what is open" and "where do I fix it." The CLI launch-proof bundle also embeds `activationPlan` from the channel activation-plan API, plus `activationPlanError` when that handoff cannot be fetched, so deploy evidence and provider setup handoff travel together. The Analytics surface also tracks SLA outcomes and speed KPIs: pending/met/breached SLA events, overdue count, average and P90 first-response minutes, and average and P90 resolution hours. `GET /api/admin/projects/{project_id}/support/launch-proof` returns the same artifact as machine-readable deploy/runtime proof before treating the workspace as launchable. `GET /api/admin/projects/{project_id}/support/launch-proof/runs` returns recent persisted proof attempts. `POST /api/admin/projects/{project_id}/support/launch-proof/run` runs all automatable blocked channel proof steps: deterministic email lifecycle proof that ingests an email, creates a ticket, queues and approves a reply, and records real delivery evidence; web chat session plus approved internal reply delivery; provider validation; HTTP inbound smoke; outbound smoke; HTTP lifecycle smoke; and external attachment-only HTTP lifecycle smoke. Manual channel config blockers remain skipped so operators still fix ticket mode, autopilot prep, default owner routing, or live provider smoke targets deliberately; target-missing external channels can still run provider credential validation, but HTTP/outbound/lifecycle smoke is skipped until real target config exists. After a run, Analytics persists the latest project-level action ledger with ran/failed/skipped counts and per-step result detail, plus recent run history, so the evidence survives reloads and operators can see which automated proof moved the workspace closer to launch readiness. Launch proof also exposes evidence ticket IDs for workflow lifecycle, human-loop automation, knowledge-assist runs, account-intelligence actions, and channel checks with created ticket artifacts, and Analytics links those rows straight back to Inbox board detail. `python -m automail.support.schema_gate` runs the PocketBase app-schema bootstrap and exits on missing support collections, fields, or migration files before launch proof runs. `python -m automail.support.launch_gate --schema-gate --bundle-file support-launch-proof.json` runs that schema preflight first, turns the launch-proof endpoint into CI/deploy exit codes, and writes a portable proof bundle for release evidence; the deploy wrapper enables this by default. `python -m automail.support.package_gate` is the static release gate for the same product spine: it checks support APIs, services, prompts, migrations, admin Pylon routes, deploy wrappers, and customer docs before the customer archive or on-prem images are produced.
Analytics readiness rows route every schema, ticket, automation, channel, email, web-chat, provider-validation, SLA, CSAT, and knowledge blocker/warning back to the surface where an operator can act on it.

Launch readiness also blocks until at least one active human-in-loop agent draft automation exists and one successful automation run proves it prepared an approval-required agent reply. This keeps the Pylon wedge centered on agent-prepared work with editor approval, not only channel plumbing. Operators can resolve `automation_proof_missing` from Analytics with `POST /api/admin/projects/{project_id}/support/automation-proof/run`, which creates a synthetic support ticket and lets the normal `issue_created` automation path prepare the approval draft.
Active channels with Autopilot prep enabled also need a successful `channel_agent_autopilot` event for that channel. The event must record a full prep package: prepared triage, custom-field preparation or an explicit no-schema skip, and a prepared approval draft with reply ID plus AI run ID. Channel launch proof therefore demonstrates that a channel-created ticket produced the human-review work package, not only that channel config, smoke paths, or a reply-only draft exist.

Ticket workflow launch proof also requires at least one existing ticket to have `status_changed` events showing the same ticket moved into `ongoing` and then `done`. Each transition stores `metadata.workflowTransition=true`, `workflowFrom`, `workflowTo`, `assigneeEmail`, and a `source` such as `inbox_board`, `inbox_detail`, or `launch_proof`, so Inbox activity can render it as lifecycle proof instead of a generic status edit. Analytics reports workflow transition counts and blocks an otherwise-ready workspace with `workflow_lifecycle_proof_missing` until the Kanban lifecycle is proven in Inbox. Operators can resolve that blocker from Analytics with `POST /api/admin/projects/{project_id}/support/workflow-proof/run`, which creates a synthetic assigned ticket and moves it through the normal `open -> ongoing -> done` issue update path so the same status-event proof is recorded.

Buffer adapter config for deterministic ingestion:

```json
{
  "adapter": "buffer",
  "inboundMessages": [
    {
      "id": "msg-1",
      "subject": "Need support",
      "fromAddress": "customer@example.com",
      "body": "Please help."
    }
  ]
}
```

IMAP adapter config:

```json
{
  "adapter": "imap",
  "host": "imap.example.com",
  "port": 993,
  "username": "support@example.com",
  "passwordEnv": "SUPPORT_IMAP_PASSWORD",
  "mailbox": "INBOX"
}
```

Operational sync:

- External cron: `POST /api/internal/support/sync` with `X-Support-Sync-Token: $SUPPORT_SYNC_TOKEN`.
- Optional in-process loop: set `SUPPORT_SYNC_INTERVAL_SECONDS` to a positive value.
- Optional scheduler scope: `SUPPORT_SYNC_TENANT_ID`, `SUPPORT_SYNC_PROJECT_ID`, `SUPPORT_SYNC_LIMIT`.
- Admin Channels shows recent `support_channel_sync_runs`.

Operational outbound delivery:

- Admin run: `POST /api/admin/projects/{project_id}/support/delivery/run`.
- Admin failed retry: `POST /api/admin/projects/{project_id}/support/delivery/run?retry_failed=true`.
- External cron: `POST /api/internal/support/delivery` with `X-Support-Sync-Token: $SUPPORT_DELIVERY_TOKEN` or fallback `$SUPPORT_SYNC_TOKEN`.
- External failed retry: include JSON body `{ "retryFailed": true }`. This is explicit; scheduled delivery keeps retrying only queued replies unless configured externally to request failed retries.
- Optional in-process loop: set `SUPPORT_DELIVERY_INTERVAL_SECONDS` to a positive value.
- Optional delivery scope: `SUPPORT_DELIVERY_TENANT_ID`, `SUPPORT_DELIVERY_PROJECT_ID`, `SUPPORT_DELIVERY_LIMIT`.
- Provider backoff: transient non-email provider responses `408`, `425`, `429`, `500`, `502`, `503`, and `504` keep the outbound reply in `queued` with `metadata.nextAttemptAt`, `deliveryAttempts`, `lastAttemptAt`, `retryAfterSeconds`, and `lastTransientError`. `Retry-After` is honored when present; Telegram-style JSON `parameters.retry_after` and similar provider JSON retry hints are also honored. Scheduled/admin delivery skips queued replies until `nextAttemptAt`.
- Provider logical errors: Slack and Telegram direct API responses with `ok=false` are treated as failed replies even when the HTTP status is 200, so agents can see and retry/fix bad channel or chat routing instead of silently marking delivery sent.
- Provider text limits: direct Slack, Discord, and Telegram payload modes split oversized replies into numbered parts before calling the provider, keeping each payload inside the provider limit. Completed multipart provider ids are stored on the outbound reply metadata so transient retries resume from the first unsent part instead of duplicating already-recorded parts. Generic adapter mode is not split because the external adapter can own splitting or file/snippet fallback.
- Provider delivery proof: successful, failed, and deferred non-email deliveries merge sanitized `deliveryRoute` and `providerResponse` metadata back onto the outbound reply. Route proof records provider/channel/transport, redacted target URL, payload mode, thread/conversation/chat ids, and part count; response proof redacts token/secret/password fields before storage.
- Inbox reply cards surface per-ticket delivery proof from outbound metadata: pre-send reply target, provider message ID, delivery receipt, attempt count, channel/thread route, retry timing, and last transient error. Sent outbound timeline messages persist the same proof metadata so ticket history remains auditable after reload.
- Admin Channels shows recent `support_delivery_runs`; delivery runs distinguish `failed`, `blocked`, `deferred`, `partial`, and `success`, and persist a concise error rollup so operators can see whether provider failures or approval blocks stopped outbound replies.
- Admin Channels exposes first-class outbound reply setup for channel adapters: `outboundWebhookUrl`, `outboundWebhookUrlEnv`, `outboundWebhookTokenEnv`, and provider/generic payload mode. Operators no longer have to discover these keys only through raw JSON.
- Admin Channels exposes setup readiness metadata for each provider: inbound URL, provider URL, auth/env presence, outbound readiness, provider-specific install steps, and a checklist that shows active/auth/outbound/test state without exposing secret values.
- Admin Channels exposes provider presets from `GET /api/admin/projects/{project_id}/channels/presets`. Presets fill channel name/key, ticket creation mode, auto-draft flags, queue defaults, outbound payload mode, env-var names, and provider adapter config for Email, Slack, Teams, Discord, Telegram, WhatsApp, Messenger, SMS, Web chat, and generic Webhook.
- Admin Channels can run explicit setup validation with `POST /api/admin/projects/{project_id}/channels/{channel_id}/validate`. Validation recomputes current runtime env readiness, inbound/outbound readiness, checklist state, and env counts without exposing secret values.
- Setup validation also probes direct provider credentials when possible: Slack `auth.test` with the configured bot token, Telegram `getMe` with the bot token, Discord `GET` against the execute-webhook URL, WhatsApp Graph phone-number identity, Messenger Graph page identity, and Twilio account identity. Failed provider probes keep the channel in `needs_setup`; skipped probes explain which env/config is missing. Validation and smoke responses now include remediation steps with severity, copyable env/config values, and rerunnable actions so operators can recover from missing env, token/scope/provider errors, no-ticket inbound smoke, outbound delivery failure, or lifecycle failure without decoding raw error text. Validation runs persist the same remediation plus a provider-validation proof artifact into sync-run history; Analytics summarizes remediation runs/items and shows latest channel fixes so ops can understand blocked channels without reopening setup panels.
- Slack OAuth install: Admin Channels can generate a signed Slack OAuth URL via `POST /api/admin/projects/{project_id}/channels/slack/install-url`. The callback exchanges the code with `oauth.v2.access`, stores `SUPPORT_SLACK_BOT_TOKEN` in project secrets, and upserts the Slack channel config. Required setup secrets: `SUPPORT_SLACK_CLIENT_ID` and `SUPPORT_SLACK_CLIENT_SECRET`; optional `SUPPORT_SLACK_OAUTH_STATE_SECRET` and `SUPPORT_SLACK_OAUTH_SCOPES`.
- Slack app manifest: Admin Channels exposes copyable manifest JSON with the OAuth redirect URL, Events API request URL, bot events, and bot scopes for configuring Slack without hand-building the app.
- Teams bridge setup: Admin Channels exposes copyable `teamsBridgeConfig` JSON with Bot Framework app env keys, validation URL template, forwarding URL, auth header, optional HMAC settings, and payload example for a Teams bot/activity bridge.
- Telegram webhook setup: saved Telegram channels can call `POST /api/admin/projects/{project_id}/channels/{channel_id}/telegram/webhook` from Admin Channels. It reads the configured bot token env plus Telegram secret-token env, calls Bot API `setWebhook`, and returns the webhook URL/result without exposing secret values.
- Discord bridge setup: Admin Channels exposes copyable `discordBridgeConfig` JSON with required gateway intents/events, bot token env key, forwarding URL, auth header, optional HMAC settings, and payload example. This is a bridge contract because Discord message events arrive over Gateway, not arbitrary outgoing webhooks.
- Discord setup readiness: the default Discord preset and setup steps now describe the bot/Gateway path end to end, including Gateway worker/sidecar forwarding, bot token env, bridge auth, lifecycle smoke, and bot reply delivery. The execute-webhook URL path is treated as a custom webhook transport, not the default.
- Bridge sidecar: `uvicorn automail.support.bridge_app:app --host 0.0.0.0 --port 8095` exposes `/bridge/teams/{channel_key}`, `/bridge/discord/{channel_key}`, and `/bridge/{provider}/{channel_key}` for Slack, Telegram, WhatsApp, Messenger, SMS/Twilio, and generic channel webhooks. It wraps provider events with project/tenant scope, signs or token-authenticates the forward request when configured, and forwards into the core `/api/internal/support/{provider}/{channel_key}` endpoints. WhatsApp and Messenger bridge routes also proxy Meta `hub.challenge` verification GETs to the core app so webhook setup can complete while the core app stays private. Admin Channels includes this contract as `metaBridgeConfig` in the install package and launch playbook.
- Discord Gateway worker: `python -m automail.support.discord_gateway` connects to Discord Gateway v10 with the configured bot token/intents, identifies, heartbeats, receives `MESSAGE_CREATE` dispatch events, and forwards raw gateway envelopes into the core Discord support endpoint.
- Admin Channels exposes a copyable install package with inbound/provider URLs, auth header/env key names, outbound config, ticketing defaults, payload examples, install steps, and readiness checklist. This lets an external Slack/Teams/Discord/Telegram adapter be configured without reading raw app JSON.
- Direct provider replies: Slack, Teams, Discord, Telegram, WhatsApp, Messenger, and SMS presets use native provider transports and require their provider credentials instead of custom outbound webhooks. Slack uses `SUPPORT_SLACK_BOT_TOKEN` with `chat.postMessage`; Telegram uses `SUPPORT_TELEGRAM_BOT_TOKEN` with `sendMessage`; Discord uses `SUPPORT_DISCORD_BOT_TOKEN`; Teams uses `SUPPORT_TEAMS_APP_ID` and `SUPPORT_TEAMS_APP_PASSWORD`; WhatsApp uses `SUPPORT_WHATSAPP_ACCESS_TOKEN` plus `SUPPORT_WHATSAPP_PHONE_NUMBER_ID`; Messenger uses `SUPPORT_MESSENGER_PAGE_ACCESS_TOKEN` plus `SUPPORT_MESSENGER_PAGE_ID`; SMS uses Twilio credentials. Legacy outbound webhook URL/template configs still work for custom adapters. Setup readiness also treats runtime bot credentials as native outbound-ready when no outbound webhook URL is configured, matching delivery runner fallback behavior.
- Non-email outbound webhooks receive top-level `channelId`, `threadId`, `sourceIssueId`, `sourceMessageId`, and `workspaceId` when the inbound channel event supplied them. The same values remain in `metadata` with contact/account context for adapters that need richer routing.
- Known non-email channels can now bypass a generic adapter: Slack sends `text` plus `channel`/`thread_ts`, Teams sends `text` plus routing ids, Discord sends `content` with safe mentions and appends `thread_id` when present, Telegram sends `chat_id`/`text` plus reply/thread ids, WhatsApp sends Cloud API text messages, Messenger sends Page Send API text messages, and SMS sends Twilio messages.
- Inbox agents can isolate tickets with failed outbound delivery via `filter=failed-delivery`, inspect the stored provider error, see deferred retry timing on queued replies, retry individual replies, or bulk retry selected failed tickets.

Operational channel webhook ingest:

- External webhook: `POST /api/internal/support/channel-webhooks/{channel_key}` with `X-Support-Sync-Token: $SUPPORT_CHANNEL_WEBHOOK_TOKEN` or fallback `$SUPPORT_SYNC_TOKEN`.
- Admin test message: `POST /api/admin/projects/{project_id}/channels/{channel_id}/test-message` durably queues a normalized message and returns `202` with a `runId` plus source identifiers. Poll `GET /api/admin/projects/{project_id}/channels/test-message-jobs/{runId}` for the terminal aggregate and created ticket/message IDs; the Admin UI also polls the issue's AI-run progress while it works.
- Admin provider smoke: `POST /api/admin/projects/{project_id}/channels/{channel_id}/smoke` validates current setup, injects a provider-native sample payload for Slack/Teams/Discord/Telegram/WhatsApp/Messenger/SMS or generic webhook, and returns readiness plus created ticket/message IDs. Default `transport=direct` calls ingestion in-process for diagnostics; `transport=http` posts to the configured inbound/provider URL with the configured token, HMAC signature, Slack signature, Telegram secret header, Meta `X-Hub-Signature-256`, or Twilio native signature. SMS setup exposes both `smsWebhookUrl` for the neutral `/api/internal/support/sms/{channel_key}` route and `providerWebhookUrl` for the provider-specific `/api/internal/support/twilio/{channel_key}` route; both feed the same Twilio form parser and signature verifier. Smoke and lifecycle smoke accept normalized `attachments`; attachment-only smoke emits provider-native attachment payloads where available, records `attachmentCount` and `fileOnly`, and proves that file-only channel messages still create tickets. Slack HTTP smoke records `X-Slack-Request-Timestamp` in the auth artifact so launch proof can show the replay-protected signing path. Telegram channels configured with `telegramSigningSecretEnv` use HMAC smoke/runtime verification in preference to the native `X-Telegram-Bot-Api-Secret-Token`, so signed-channel launch proof cannot accidentally pass with token auth. WhatsApp and Messenger channels configured with Meta app secrets use HMAC smoke/runtime verification in preference to token fallback. SMS channels with a configured Twilio Auth Token must record `twilio_signature` auth in launch proof, so token-auth bridge smokes cannot pass as direct Twilio provider proof. External channel launch proof requires real configured smoke targets, HTTP inbound smoke, HTTP lifecycle smoke, and attachment-only HTTP lifecycle smoke. Direct runs do not mark the channel launch-ready.
- Launch proof artifacts: inbound and lifecycle smoke must record a created ticket ID; lifecycle smoke must record the approved reply ID. Route-addressed inbound smoke records target proof such as Slack channel/thread, Teams conversation, Discord channel, or Telegram chat. Channels configured for provider-shaped or native bot outbound delivery (`outboundPayloadMode=provider` or `outboundTransport=bot/provider_api`) must also configure live provider smoke targets and record `providerMessageId`, sanitized `deliveryRoute`, and sanitized `providerResponse` on outbound and lifecycle smoke, so launch readiness proves the provider accepted the reply and not only that the app queued it. Those artifacts must match the current live target config; changing `smokeChannelId`, Teams conversation/service URL, chat ID, PSID, or phone recipient invalidates older provider proof until smoke is rerun. The same target and delivery proof is required when native bot delivery is inferred from runtime bot credentials and no outbound webhook URL is configured.
- Human-in-loop automation proof: launch readiness requires an active automation whose action prepares an agent reply with approval required, plus a successful run that records a prepared reply ID.
- Per-channel signature mode: set channel config `signatureSecretEnv` to an env var name, then send `X-Support-Signature: sha256=<hmac_sha256(secret, raw_body)>`. Override the header with channel config `signatureHeader`.
- Replay-protected signature mode: set `signatureTimestampRequired=true`, optionally set `signatureTimestampHeader` and `signatureToleranceSeconds`, then sign `"{timestamp}.{raw_body}"`. The bridge sidecar emits timestamp-bound signatures by default when `SUPPORT_BRIDGE_SIGNATURE_SECRET` or `SUPPORT_BRIDGE_SIGNATURE_SECRET_ENV` is configured.
- Runtime secret lookup: token/signature names such as `SUPPORT_CHANNEL_WEBHOOK_TOKEN`, `SUPPORT_SLACK_WEBHOOK_TOKEN`, `SUPPORT_TELEGRAM_SECRET_TOKEN`, and `signatureSecretEnv` values are resolved from tenant/project secrets first, then process env. Admin Channels setup readiness uses the same lookup without exposing secret values.
- Per-channel token key: set channel config `webhookTokenEnv` to override the default inbound token name for generic and provider webhooks. This lets each Slack/Teams/Discord/Telegram channel use its own project-secret key instead of sharing one global token.
- Optional scope: pass `tenantId` and `projectId` in the JSON body or `tenant_id` and `project_id` query params.
- Wrapped payload shape: `{ "tenantId": "...", "projectId": "...", "payload": { ... } }`.
- Raw payload shape: direct event object or `{ "events": [...] }`.
- Delivery receipt matching: `providerMessageId`, `provider_message_id`, `messageId`, `message_id`, `smtpMessageId`, `emailId`, `sg_message_id`, or explicit `outboundMessageId`.
- Event idempotency: processed events are keyed by channel + event id and skipped on replay.
- Admin Channels shows recent `support_channel_webhook_events`.

Operational web chat:

- Widget page: `GET /support/web-chat/{project_id}?channel_key=web-chat`.
- Embeddable widget script: `GET /support/web-chat/{project_id}/embed.js?channel_key=web-chat`. Install with `<script async src="..."></script>` on a customer-facing site; the script opens the hosted widget in an iframe using the script origin, passes the customer page URL/title/referrer into web-chat session metadata, and records the latest ticket ID plus ticket/message counts on the launcher root after the hosted iframe posts session status back.
- Create session: `POST /api/support/web-chat/{project_id}/sessions`.
- Read session: `GET /api/support/web-chat/sessions/{session_key}`.
- Append visitor message: `POST /api/support/web-chat/sessions/{session_key}/messages`.
- Help articles: hosted and embedded web chat call the public help-center API and let visitors search/open published Knowledge articles before or during chat.
- New sessions create an Inbox issue with `channel=web_chat`, normalized timeline message, SLA clocks, and account/contact read models when visitor identity is present.
- Web chat follow-up messages default to session/thread updates, but `ticketCreationMode=per_message` can turn each visitor message into a new Inbox issue while preserving the web-chat session link.
- Admin Channels shows recent `support_web_chat_sessions`.

Operational public help center:

- Page: `GET /support/knowledge/{project_id}`.
- Article page: `GET /support/knowledge/{project_id}/articles/{article_id}`.
- JSON list/search: `GET /api/support/knowledge/{project_id}?q=reset`.
- JSON article: `GET /api/support/knowledge/{project_id}/articles/{article_id}`.
- Only `published` Knowledge articles are exposed. Articles with metadata `visibility=internal`, `visibility=private`, or `public=false` stay private.

Operational Slack ingest:

- External event URL: `POST /api/internal/support/slack/{channel_key}`.
- Direct Slack auth: set `SUPPORT_SLACK_SIGNING_SECRET` to verify `X-Slack-Signature`.
- Per-channel Slack auth: set channel config `slackSigningSecretEnv` to an env var name to support multiple Slack workspaces with different signing secrets. `signatureSecretEnv` is also accepted and uses Slack's native `v0:{timestamp}:{raw_body}` signing base on the Slack provider endpoint.
- Gateway/token auth: set `SUPPORT_SLACK_WEBHOOK_TOKEN` or fallback `SUPPORT_SYNC_TOKEN`, then send `X-Support-Sync-Token`. This is a fallback only when no Slack signing secret is configured or present; if `SUPPORT_SLACK_SIGNING_SECRET` exists, runtime and setup prefer Slack signature proof.
- URL verification returns the Slack `challenge`.
- Optional scope: pass `tenantId` and `projectId` in wrapped JSON or `tenant_id` and `project_id` query params.
- Channel config sketch:

```json
{
  "adapter": "slack",
  "teamId": "T123",
  "ticketCreationMode": "per_message",
  "slackSigningSecretEnv": "ACME_SLACK_SIGNING_SECRET",
  "autoPrepareAgentReply": true,
  "autoPrepareAgentReplyOnUpdate": true,
  "agentAutoSend": false,
  "workspaceName": "Acme Slack",
  "botUserId": "U_BOT",
  "outboundTransport": "bot",
  "slackBotTokenEnv": "SUPPORT_SLACK_BOT_TOKEN",
  "userNames": {
    "U123": "Ana"
  }
}
```

- Message events create or update an Inbox issue with `channel=slack`, source key `slack:{team}:{channel}:{thread_ts}`, normalized timeline messages, SLA clocks on new issues, and account/contact read models keyed to the Slack workspace/user.
- With `ticketCreationMode=per_message`, Slack issue source keys use the event timestamp instead of `thread_ts`, so every Slack message can become a separate ticket while preserving `threadTs` for replies.
- File-only Slack messages also create tickets. The timeline body is synthesized from attachment filenames while normalized file metadata stays on the message.
- Bot, changed, deleted, join, and leave messages are ignored.

Operational Teams ingest:

- External event URL: `POST /api/internal/support/teams/{channel_key}` with `X-Support-Sync-Token: $SUPPORT_TEAMS_WEBHOOK_TOKEN` or fallback `$SUPPORT_SYNC_TOKEN`.
- Admin Channels exposes `teamsBridgeConfig` for a Bot Framework/activity bridge that receives Teams message activities, forwards them to the external event URL, and uses the validation URL template for validation-token flows.
- Deployable bridge sidecar: run `uvicorn automail.support.bridge_app:app --host 0.0.0.0 --port 8095`, set `SUPPORT_BRIDGE_CORE_URL`, `SUPPORT_BRIDGE_PROJECT_ID`, optional `SUPPORT_BRIDGE_TENANT_ID`, and optionally `SUPPORT_BRIDGE_TOKEN_ENV=SUPPORT_TEAMS_WEBHOOK_TOKEN`. The sidecar route `/bridge/teams/{channel_key}` echoes `validationToken` on GET and forwards POSTed activity JSON to the core Teams endpoint. Without an override, the sidecar uses the provider token env for each route.
- Optional per-channel HMAC: set channel config `teamsSigningSecretEnv` or fallback `signatureSecretEnv`, and optionally `signatureHeader`; the provider endpoint verifies `sha256=<hmac_sha256(secret, raw_body)>` before ingestion. Use `signatureTimestampRequired=true` for timestamp-bound signatures from the bridge sidecar. Use this when a Teams bridge/adapter can sign forwarded activity payloads.
- Validation URL: `GET /api/internal/support/teams/{channel_key}?validationToken=...` returns the token as plain text for validation flows that require it.
- Optional bridge config keys: `teamsAppIdEnv`, `teamsAppPasswordEnv`, and `activityTypes`.
- Optional scope: pass `tenantId` and `projectId` in wrapped JSON or `tenant_id` and `project_id` query params.
- Channel config sketch:

```json
{
  "adapter": "teams",
  "teamId": "team-1",
  "ticketCreationMode": "per_message",
  "signatureSecretEnv": "ACME_TEAMS_SIGNING_SECRET",
  "autoPrepareAgentReply": true,
  "autoPrepareAgentReplyOnUpdate": true,
  "agentAutoSend": false,
  "teamName": "Acme Teams",
  "botUserId": "bot-1",
  "outboundTransport": "bot",
  "teamsAppIdEnv": "SUPPORT_TEAMS_APP_ID",
  "teamsAppPasswordEnv": "SUPPORT_TEAMS_APP_PASSWORD"
}
```

- Message activities create or update an Inbox issue with `channel=teams`, source key `teams:{team}:{channel}:{conversation_or_thread}`, normalized timeline messages, SLA clocks on new issues, and account/contact read models keyed to the Teams workspace/user.
- With `ticketCreationMode=per_message`, Teams issue source keys use the activity message id instead of the conversation id, so each activity can become a separate ticket while preserving `threadId` for replies.
- Non-message activities and self messages are ignored.

Operational Discord ingest:

- External event URL: `POST /api/internal/support/discord/{channel_key}` with `X-Support-Sync-Token: $SUPPORT_DISCORD_WEBHOOK_TOKEN` or fallback `$SUPPORT_SYNC_TOKEN`.
- Admin Channels exposes `discordBridgeConfig` for a gateway bridge that listens to `MESSAGE_CREATE` using `GuildMessages`, `DirectMessages`, and `MessageContent`, then forwards the raw gateway event to the external event URL.
- Deployable bridge sidecar: run `uvicorn automail.support.bridge_app:app --host 0.0.0.0 --port 8095`, set `SUPPORT_BRIDGE_CORE_URL`, `SUPPORT_BRIDGE_PROJECT_ID`, optional `SUPPORT_BRIDGE_TENANT_ID`, and optionally `SUPPORT_BRIDGE_TOKEN_ENV=SUPPORT_DISCORD_WEBHOOK_TOKEN`. A Discord gateway worker can POST raw `MESSAGE_CREATE` envelopes to `/bridge/discord/{channel_key}` and the sidecar forwards them to the core Discord endpoint. Without an override, the sidecar uses the provider token env for each route.
- Built-in Gateway worker: run `python -m automail.support.discord_gateway`, set `SUPPORT_DISCORD_BOT_TOKEN`, `SUPPORT_BRIDGE_CORE_URL`, `SUPPORT_BRIDGE_PROJECT_ID`, `SUPPORT_BRIDGE_DISCORD_CHANNEL_KEY`, and `SUPPORT_BRIDGE_TOKEN_ENV=SUPPORT_DISCORD_WEBHOOK_TOKEN`. Optional env: `SUPPORT_BRIDGE_DISCORD_GATEWAY_EVENTS`, `SUPPORT_BRIDGE_DISCORD_GATEWAY_INTENTS`, `SUPPORT_BRIDGE_DISCORD_GATEWAY_URL`, and `SUPPORT_BRIDGE_RECONNECT_SECONDS`.
- Default worker intents: `GUILDS`, `GUILD_MESSAGES`, `DIRECT_MESSAGES`, and `MESSAGE_CONTENT`. Message content is privileged in Discord and must be enabled/approved before the worker can receive user-generated message text.
- Optional per-channel HMAC: set channel config `discordSigningSecretEnv` or fallback `signatureSecretEnv`, and optionally `signatureHeader`; the provider endpoint verifies `sha256=<hmac_sha256(secret, raw_body)>` before ingestion. Use `signatureTimestampRequired=true` for timestamp-bound signatures from the bridge sidecar.
- Optional bridge config keys: `discordBotTokenEnv`, `gatewayIntents`, and `gatewayEvents`.
- Optional scope: pass `tenantId` and `projectId` in wrapped JSON or `tenant_id` and `project_id` query params.
- The endpoint feeds Discord-shaped payloads into normalized channel webhook ingest, including `MESSAGE_CREATE` gateway-style envelopes with a `d` object or direct message objects with `content`, `channel_id`, `guild_id`, and `author`.
- Messages create or update Inbox tickets with `channel=discord`; `ticketCreationMode=per_message` keeps each Discord message as its own ticket while preserving channel/thread ids for replies.

Operational Telegram ingest:

- External event URL: `POST /api/internal/support/telegram/{channel_key}` with `X-Support-Sync-Token: $SUPPORT_TELEGRAM_WEBHOOK_TOKEN` or fallback `$SUPPORT_SYNC_TOKEN`.
- Native secret token: set `SUPPORT_TELEGRAM_SECRET_TOKEN`; Telegram must send `X-Telegram-Bot-Api-Secret-Token` with the same value. For multiple bots, set channel config `telegramSecretTokenEnv` to a per-channel project-secret key.
- Admin setup: the Channels page can register the Bot API webhook when `SUPPORT_TELEGRAM_BOT_TOKEN` and the configured secret-token env are present.
- Optional per-channel HMAC fallback: when no Telegram secret token is configured, set channel config `telegramSigningSecretEnv` or fallback `signatureSecretEnv`, and optionally `signatureHeader`. Use `signatureTimestampRequired=true` for timestamp-bound signed adapter requests.
- Optional scope: pass `tenantId` and `projectId` in wrapped JSON or `tenant_id` and `project_id` query params.
- The endpoint feeds Telegram update payloads into normalized channel webhook ingest, including `message.text`, `message.chat.id`, and `message.from`.
- Messages create or update Inbox tickets with `channel=telegram`; `ticketCreationMode=per_message` keeps each Telegram message as its own ticket while preserving chat/thread ids for replies.

Operational WhatsApp ingest:

- External event URL: `GET/POST /api/internal/support/whatsapp/{channel_key}`.
- Webhook verification: set `SUPPORT_WHATSAPP_VERIFY_TOKEN` or channel config `whatsappVerifyTokenEnv`; Meta `hub.challenge` returns as plain text when the verify token matches.
- Deployable bridge sidecar: `GET /bridge/whatsapp/{channel_key}` proxies Meta verification query params to the core WhatsApp endpoint and returns the plain challenge text; `POST /bridge/whatsapp/{channel_key}` forwards Cloud API webhook events. Admin Channels exposes the copyable `metaBridgeConfig` with public path, sidecar env, validation query params, forward target, and bridge-signature settings.
- Native Meta signature: set `SUPPORT_WHATSAPP_APP_SECRET` or channel config `whatsappSigningSecretEnv`; runtime and HTTP smoke verify `X-Hub-Signature-256: sha256=<hmac_sha256(app_secret, raw_body)>`.
- Token fallback: set `SUPPORT_WHATSAPP_WEBHOOK_TOKEN` or fallback `SUPPORT_SYNC_TOKEN` only when no WhatsApp app secret is configured.
- Native replies: set `SUPPORT_WHATSAPP_PHONE_NUMBER_ID` plus `SUPPORT_WHATSAPP_ACCESS_TOKEN`; delivery posts Cloud API text payloads and records provider message IDs as `whatsapp:{message_id}`.
- Cloud API messages create Inbox tickets with `channel=whatsapp`; `ticketCreationMode=per_message` keeps each customer message as its own ticket while preserving WA ID and phone-number ids for replies.

Operational Messenger ingest:

- External event URL: `GET/POST /api/internal/support/messenger/{channel_key}`.
- Webhook verification: set `SUPPORT_MESSENGER_VERIFY_TOKEN` or channel config `messengerVerifyTokenEnv`; Meta `hub.challenge` returns as plain text when the verify token matches.
- Deployable bridge sidecar: `GET /bridge/messenger/{channel_key}` proxies Meta verification query params to the core Messenger endpoint and returns the plain challenge text; `POST /bridge/messenger/{channel_key}` forwards page webhook events. Admin Channels exposes the copyable `metaBridgeConfig` with public path, sidecar env, validation query params, forward target, and bridge-signature settings.
- Native Meta signature: set `SUPPORT_MESSENGER_APP_SECRET` or channel config `messengerSigningSecretEnv`; runtime and HTTP smoke verify `X-Hub-Signature-256: sha256=<hmac_sha256(app_secret, raw_body)>`.
- Token fallback: set `SUPPORT_MESSENGER_WEBHOOK_TOKEN` or fallback `SUPPORT_SYNC_TOKEN` only when no Messenger app secret is configured.
- Native replies: set `SUPPORT_MESSENGER_PAGE_ID` plus `SUPPORT_MESSENGER_PAGE_ACCESS_TOKEN`; delivery posts Page Send API text payloads to Graph `/messages` and records provider message IDs as `messenger:{message_id}`.
- Page webhook messages create Inbox tickets with `channel=messenger`; `ticketCreationMode=per_message` keeps each customer PSID message as its own ticket while preserving PSID/page ids for replies.

## CRM Sync

Admin Channels can store CRM connectors and run account/contact sync. Synced CRM records update `support_accounts`, `support_contacts`, and `support_external_objects`, then record `support_external_sync_runs` for account detail visibility.

Admin Channels includes setup presets for HubSpot, Salesforce, and generic HTTPS CRM polling. Choosing a provider pre-fills connector key/name, adapter config, and required runtime secret env names, while still allowing raw JSON edits for custom connectors.
Saved CRM connectors can be validated before sync. Validation checks required runtime secrets and performs a lightweight provider read (`companies`/`contacts` for HubSpot, `Account`/`Contact` SOQL for Salesforce, one-record endpoint read for generic HTTPS) without returning or storing secret values.
Admin Accounts exposes CRM health on account detail: linked providers, external record count, latest sync, failed/partial sync attention, and direct external record links.
Project launch proof treats failed CRM/external sync runs as a launch warning and can run `crm_sync_recovery` to retry active CRM connector polling from the Analytics control center. If no active CRM connector exists, the proof action is recorded as skipped so stale external-object failures remain visible instead of being marked fixed without a real sync path.

Low CSAT is treated as account-risk evidence, not only a support KPI. Project launch proof can run `low_csat_followups` from Analytics to make affected tickets actionable again: priority is raised, closed tickets move back to `ongoing`, unassigned tickets get the current operator, an internal note records the recovery checklist, and the related account receives an idempotent `low-csat:{issueId}` risk insight.

Buffer adapter config for deterministic CRM sync:

```json
{
  "adapter": "buffer",
  "accounts": [
    {
      "id": "acc-1",
      "name": "Acme",
      "domain": "acme.example",
      "url": "https://crm.example/accounts/acc-1",
      "contacts": [
        {
          "id": "person-1",
          "email": "ana@acme.example",
          "name": "Ana Acme"
        }
      ]
    }
  ]
}
```

HubSpot private-app polling config:

```json
{
  "adapter": "hubspot",
  "privateAppTokenEnv": "HUBSPOT_PRIVATE_APP_TOKEN",
  "portalId": "12345678"
}
```

The adapter reads companies and contacts through HubSpot CRM search, stores the cursor by `hs_lastmodifieddate`, and writes normalized accounts, contacts, and external CRM objects without persisting the private app token.

Salesforce REST polling config:

```json
{
  "adapter": "salesforce",
  "accessTokenEnv": "SALESFORCE_ACCESS_TOKEN",
  "instanceUrlEnv": "SALESFORCE_INSTANCE_URL",
  "apiVersion": "v61.0"
}
```

The adapter reads Account and Contact records through Salesforce SOQL, stores the cursor by `SystemModstamp`, and writes normalized accounts, contacts, and external CRM objects without persisting the Salesforce token.

Generic HTTPS polling config:

```json
{
  "adapter": "http",
  "endpointUrl": "https://crm.example.com/api/support/accounts",
  "tokenEnv": "CRM_HTTP_TOKEN",
  "recordsPath": "items",
  "cursorPath": "updatedAt",
  "cursorParam": "cursor",
  "limitParam": "limit"
}
```

The adapter sends `cursor` and `limit` query params, reads records from `recordsPath`, normalizes account/contact fields using the same webhook schema, stores per-record cursor values, and writes account/contact/external-object records without persisting the API token. Non-HTTPS endpoints are rejected unless explicitly marked `allowInsecureHttp` for local development.

Operational CRM sync:

- Admin run: `POST /api/admin/projects/{project_id}/crm/connectors/sync/run`.
- External cron: `POST /api/internal/support/crm-sync` with `X-Support-Sync-Token: $SUPPORT_CRM_SYNC_TOKEN` or fallback `$SUPPORT_SYNC_TOKEN`.
- Optional in-process loop: set `SUPPORT_CRM_SYNC_INTERVAL_SECONDS` to a positive value.
- Optional scheduler scope: `SUPPORT_CRM_SYNC_TENANT_ID`, `SUPPORT_CRM_SYNC_PROJECT_ID`, `SUPPORT_CRM_SYNC_LIMIT`.
- Admin Channels shows recent `support_crm_sync_runs`.

Operational CRM webhook ingest:

- External webhook: `POST /api/internal/support/crm-webhooks/{connector_key}` with `X-Support-Sync-Token: $SUPPORT_CRM_WEBHOOK_TOKEN` or fallback `$SUPPORT_SYNC_TOKEN`.
- Optional scope: pass `tenantId` and `projectId` in the JSON body or `tenant_id` and `project_id` query params.
- Wrapped payload shape: `{ "tenantId": "...", "projectId": "...", "payload": { ... } }`.
- Raw payload shape: direct event object or `{ "events": [...] }`.
- Event idempotency: processed events are keyed by connector + event id and skipped on replay.
- Admin Channels shows recent `support_crm_webhook_events`.
