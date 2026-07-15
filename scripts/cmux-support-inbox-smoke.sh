#!/bin/sh

set -eu

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
API_PORT="${SUPPORT_INBOX_SMOKE_API_PORT:-5181}"
ADMIN_PORT="${SUPPORT_INBOX_SMOKE_ADMIN_PORT:-5179}"
API_URL="http://127.0.0.1:${API_PORT}"
ADMIN_URL="http://127.0.0.1:${ADMIN_PORT}"
API_LOG="${TMPDIR:-/tmp}/support-inbox-smoke-api.log"
ADMIN_LOG="${TMPDIR:-/tmp}/support-inbox-smoke-admin.log"
BODY_TEXT="${TMPDIR:-/tmp}/support-inbox-smoke-body.txt"
SURFACE=""

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 1
  fi
}

wait_for_url() {
  url="$1"
  label="$2"
  attempts="${3:-60}"
  i=0
  until curl -fsS "$url" >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge "$attempts" ]; then
      echo "timed out waiting for $label at $url" >&2
      exit 1
    fi
    sleep 1
  done
}

assert_text() {
  needle="$1"
  if ! grep -F -- "$needle" "$BODY_TEXT" >/dev/null 2>&1; then
    echo "expected DOM text missing: $needle" >&2
    echo "--- body text ---" >&2
    sed -n '1,220p' "$BODY_TEXT" >&2
    exit 1
  fi
}

assert_absent() {
  needle="$1"
  if grep -F -- "$needle" "$BODY_TEXT" >/dev/null 2>&1; then
    echo "unexpected DOM text present: $needle" >&2
    echo "--- body text ---" >&2
    sed -n '1,220p' "$BODY_TEXT" >&2
    exit 1
  fi
}

capture_body() {
  cmux browser "$SURFACE" eval "document.body.textContent" >"$BODY_TEXT"
}

cleanup() {
  if [ -n "$SURFACE" ]; then
    cmux browser "$SURFACE" tab close >/dev/null 2>&1 || true
  fi
  if [ -n "${ADMIN_PID:-}" ]; then kill "$ADMIN_PID" >/dev/null 2>&1 || true; fi
  if [ -n "${API_PID:-}" ]; then kill "$API_PID" >/dev/null 2>&1 || true; fi
}

trap cleanup EXIT INT TERM

require_cmd cmux
require_cmd node
require_cmd npm
require_cmd curl

rm -f "$API_LOG" "$ADMIN_LOG" "$BODY_TEXT"

PORT="$API_PORT" node "$ROOT_DIR/scripts/support-inbox-smoke-api.mjs" >"$API_LOG" 2>&1 &
API_PID=$!
wait_for_url "$API_URL/api/health" "support inbox smoke api" 30

(
  cd "$ROOT_DIR/admin"
  VITE_API_URL="$API_URL" \
  VITE_REQUIRE_AUTH=false \
  npm run dev -- --host 127.0.0.1 --port "$ADMIN_PORT" >"$ADMIN_LOG" 2>&1
) &
ADMIN_PID=$!
wait_for_url "$ADMIN_URL" "admin vite" 60

OPEN_OUTPUT="$(cmux browser open "$ADMIN_URL/tenant1/project1/inbox/issue-discord-open?view=board")"
SURFACE="$(printf '%s\n' "$OPEN_OUTPUT" | sed -n 's/.*surface=\([^ ]*\).*/\1/p')"
if [ -z "$SURFACE" ]; then
  echo "could not parse cmux surface from: $OPEN_OUTPUT" >&2
  exit 1
fi

cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Discord incident: production API down')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "Array.from(document.querySelectorAll('h1,h2')).some((el) => el.textContent.includes('Discord incident: production API down')) && document.body.textContent.includes('Approval required') && document.body.textContent.includes('Ask agent')" --timeout-ms 15000 >/dev/null
capture_body

assert_text "Inbox"
assert_text "3 tickets"
assert_text "Open"
assert_text "Ongoing"
assert_text "Done"
assert_text "Discord incident: production API down"
assert_text "Telegram billing question"
assert_text "Email setup solved"
assert_text "Ask agent"
assert_text "Queue if safe"
assert_text "Knowledge"
assert_text "Message timeline"
assert_text "Reply"
assert_text "Approval required"
assert_text "API outage response checklist"
assert_text "Autopilot proof"
assert_text "Complete"
assert_text "Custom fields"
assert_text "Draft reply"
assert_text "Account intelligence"
assert_text "Acme Cloud"
assert_text "Support views"
assert_text "Needs assignee"
assert_text "Overdue SLA"
assert_absent "Package incomplete"
assert_absent "No response from server"

cmux browser "$SURFACE" click "[data-inbox-support-view='overdue-sla']" >/dev/null
cmux browser "$SURFACE" wait --function "location.search.includes('filter=overdue-sla') && location.search.includes('view=list') && document.querySelector('[data-inbox-support-view=\"overdue-sla\"]')?.getAttribute('data-inbox-support-view-active') === 'true'" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Support views"
assert_text "Overdue SLA"

cmux browser "$SURFACE" click "[data-inbox-support-view='needs-response']" >/dev/null
cmux browser "$SURFACE" wait --function "location.search.includes('filter=needs-response') && !location.search.includes('view=list') && document.querySelector('[data-inbox-support-view=\"needs-response\"]')?.getAttribute('data-inbox-support-view-active') === 'true'" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Needs response"
assert_text "Discord incident: production API down"

cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-inbox-notification=\"notification-1\"]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval "document.querySelector('[data-inbox-notification=\"notification-1\"]').click()" >/dev/null
cmux browser "$SURFACE" wait --function "!document.querySelector('[data-inbox-notification=\"notification-1\"]')" --timeout-ms 15000 >/dev/null

cmux browser "$SURFACE" click "[data-ticket-watch-toggle]" >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-ticket-watcher-email=\"agent@example.com\"]'))" --timeout-ms 15000 >/dev/null

cmux browser "$SURFACE" eval "(() => { const el = document.querySelector('[data-ticket-internal-note-input]'); const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set; setter.call(el, 'Internal handoff note from smoke.'); el.dispatchEvent(new Event('input', { bubbles: true })); })()" >/dev/null
cmux browser "$SURFACE" wait --function "!document.querySelector('[data-ticket-internal-note-submit]')?.disabled" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-ticket-internal-note-submit]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Internal handoff note from smoke.')" --timeout-ms 15000 >/dev/null

cmux browser "$SURFACE" click "[data-reply-macro-select]" >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-reply-macro-option=\"macro-incident\"]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-reply-macro-option='macro-incident']" >/dev/null
cmux browser "$SURFACE" click "[data-reply-macro-insert]" >/dev/null
cmux browser "$SURFACE" wait --function "Array.from(document.querySelectorAll('[data-ticket-reply-draft]')).some(el => el.value.includes('Thanks for the report. We are investigating'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-reply-macro-save-open]" >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-reply-macro-title]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval "(() => { const el = document.querySelector('[data-reply-macro-title]'); const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set; setter.call(el, 'Smoke saved macro'); el.dispatchEvent(new Event('input', { bubbles: true })); })()" >/dev/null
cmux browser "$SURFACE" click "[data-reply-macro-save-submit]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Smoke saved macro')" --timeout-ms 15000 >/dev/null

cmux browser "$SURFACE" click "[data-inbox-save-view-open]" >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-inbox-save-view-name]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval "(() => { const el = document.querySelector('[data-inbox-save-view-name]'); const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set; setter.call(el, 'Smoke collaboration view'); el.dispatchEvent(new Event('input', { bubbles: true })); })()" >/dev/null
cmux browser "$SURFACE" click "[data-inbox-save-view-submit]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Smoke collaboration view')" --timeout-ms 15000 >/dev/null

capture_body
assert_text "agent@example.com"
assert_text "manual"
assert_text "Internal handoff note from smoke."
assert_text "Smoke saved macro"
assert_text "Smoke collaboration view"

cmux browser "$SURFACE" click "[data-ticket-draft-knowledge-article='gap-discord-eta']" >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-ticket-knowledge-article=\"kb-smoke-1\"]')) && document.body.textContent.includes('API incident ETA policy')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval "(() => { const button = Array.from(document.querySelectorAll('[data-ticket-knowledge-publish=\"kb-smoke-1\"]')).find((item) => item.offsetParent !== null && !item.disabled); if (!button) throw new Error('ticket knowledge publish button missing'); button.click(); })()" >/dev/null
cmux browser "$SURFACE" wait --function "(() => { const card = document.querySelector('[data-ticket-knowledge-article=\"kb-smoke-1\"]'); const text = card?.textContent.toLowerCase() || ''; return Boolean(card && text.includes('published') && text.includes('public') && !document.querySelector('[data-ticket-knowledge-publish=\"kb-smoke-1\"]')); })()" --timeout-ms 15000 >/dev/null
capture_body
assert_text "API incident ETA policy"
assert_text "Customer evidence:"
assert_text "published"
assert_text "Public"

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/knowledge" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-knowledge-gap-create=\"gap-discord-runbook\"]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-knowledge-gap-create='gap-discord-runbook']" >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-knowledge-publish-public]')) && document.body.textContent.includes('API incident ownership policy') && document.body.textContent.includes('Source ticket')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "API incident ownership policy"
assert_text "Escalation owner and customer-update cadence are not documented for API incidents."
cmux browser "$SURFACE" wait --function "document.querySelector('[data-knowledge-article-source-ticket]')?.value === 'issue-discord-open'" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-knowledge-publish-public]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('published') && document.body.textContent.includes('public') && document.body.textContent.includes('Revision history')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "published"
assert_text "public"
assert_text "Revision history"
assert_text "Revision 2"
cmux browser "$SURFACE" navigate "$API_URL/support/knowledge/project1" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Support knowledge') && document.body.textContent.includes('API incident ownership policy')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Support knowledge"
assert_text "API incident ownership policy"
assert_text "Escalation owner and customer-update cadence are not documented for API incidents."

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/inbox/issue-discord-open?view=board" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-ticket-account-risk]'))" --timeout-ms 15000 >/dev/null

cmux browser "$SURFACE" click "[data-ticket-account-risk]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Risk added')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-ticket-account-feature-request]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Feature request added')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-ticket-account-insight-resolve]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval "(() => { const button = Array.from(document.querySelectorAll('[data-ticket-account-insight-resolve]')).find((item) => item.offsetParent !== null && !item.disabled); if (!button) throw new Error('account insight resolve button missing'); button.click(); })()" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Insight resolved')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Risks"
assert_text "Requests"
assert_text "Signals"
assert_text "Insight resolved"

cmux browser "$SURFACE" click "[data-ticket-create-portal-link]" >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-ticket-portal-url]')?.href)" --timeout-ms 15000 >/dev/null
PORTAL_URL="$(cmux browser "$SURFACE" eval "document.querySelector('[data-ticket-portal-url]').href")"
if [ -z "$PORTAL_URL" ]; then
  echo "portal URL missing" >&2
  exit 1
fi
capture_body
assert_text "Portal link created"
assert_text "portal-smoke-1"

cmux browser "$SURFACE" navigate "$PORTAL_URL" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Customer portal') && document.body.textContent.includes('API outage response checklist')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Customer portal"
assert_text "Discord incident: production API down"
assert_text "Help articles"
assert_text "API outage response checklist"
cmux browser "$SURFACE" eval "document.querySelector('[data-article-id=\"kb-api-outage\"]').click()" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Confirm current incident status')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval "(() => { document.querySelector('#body').value = 'Portal customer follow-up from smoke.'; document.querySelector('#send').click(); })()" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Message sent.')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval "(() => { document.querySelector('[data-rating=\"2\"]').click(); document.querySelector('#feedbackComment').value = 'Still blocked after outage.'; document.querySelector('#submitFeedback').click(); })()" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Rating saved.')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Message sent."
assert_text "Rating saved."

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/inbox/issue-discord-open?view=board&filter=low-csat" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Portal customer follow-up from smoke.') && document.body.textContent.includes('Still blocked after outage.')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Low CSAT"
assert_text "Portal customer follow-up from smoke."
assert_text "Still blocked after outage."
assert_text "2/5"

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/accounts/account-acme" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Account operations') && document.body.textContent.includes('Support risk: Discord incident: production API down')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Accounts"
assert_text "Account operations"
assert_text "Support health, CRM sync, and feature-demand signals across all accounts."
assert_text "Acme Cloud"
assert_text "at_risk"
assert_text "Health rollup"
assert_text "Assign an owner, confirm the customer update, and close the risk loop."
assert_text "API outage risk"
assert_text "Support risk: Discord incident: production API down"
assert_text "Feature request: Discord incident: production API down"
assert_text "No external records"

cmux browser "$SURFACE" click "[data-account-crm-sync]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('CRM sync result') && document.body.textContent.includes('Acme Cloud HubSpot company')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "CRM sync result"
assert_text "1 connectors"
assert_text "1 processed"
assert_text "1 objects"
assert_text "CRM linked"
assert_text "Acme Cloud HubSpot company"
assert_text "hubspot-company-123"

cmux browser "$SURFACE" click "[data-generate-account-summary]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Generated account summary: Acme Cloud')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Generated account summary: Acme Cloud"

cmux browser "$SURFACE" click "[data-account-insight-resolve='insight-smoke-1']" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('resolved')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "resolved"

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/analytics" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('SLA performance') && document.body.textContent.includes('Launch proof')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Analytics"
assert_text "Export CSV"
assert_text "Export proof"
assert_text "Launch readiness"
assert_text "Launch proof"
assert_text "Schema health"
assert_text "Support health"
assert_text "SLA risk"
assert_text "First response"
assert_text "Support workload"
assert_text "SLA performance"
assert_text "Overdue SLA"
assert_text "SLA due soon"
assert_text "Avg first response min"
assert_text "P90 resolution hours"
assert_text "Channel smoke"
assert_text "Live smoke target"
assert_text "Ticket creation proof"
assert_text "Reply-route proof"
assert_text "Human-loop proof"
assert_text "Agent prepares, editor approves"
assert_text "Channel autopilot proof"
assert_text "Channel agent prepares review package"
assert_text "Knowledge assist proof"
assert_text "Agent answers cite KB or record gaps"
assert_text "Account intelligence proof"
assert_text "Account health, risk, and demand signals"
assert_text "Ticket workflow proof"
assert_text "Open to ongoing to done"
assert_text "Every-message ticketing"
assert_text "Wrong ticket mode"
assert_text "Reply-route ready"
assert_text "Email sync proof"
assert_text "Email delivery proof"
assert_text "Attachment lifecycle proof"
assert_text "Missing attachment lifecycle proof"
assert_text "Web chat session proof"
assert_text "Missing web chat session proof"
assert_text "Web chat delivery proof"
assert_text "Missing web chat delivery proof"
assert_text "Account insights"
cmux browser "$SURFACE" wait --function "(() => { const link = document.querySelector('[data-support-report-download]'); if (!link) return false; const csv = decodeURIComponent(link.href); return link.getAttribute('download') === 'support-report-project1.csv' && csv.includes('\"section\",\"metric\",\"value\"') && csv.includes('\"Workload\",\"Active tickets\"') && csv.includes('\"Workflow\",\"Ticket workflow proof ready\"') && csv.includes('\"Workflow\",\"Ticket workflow proof blocked\"') && csv.includes('\"SLA\",\"Overdue SLA\"') && csv.includes('\"Channels\",\"Active channels\"') && csv.includes('\"Channels\",\"Every-message ticketing\"') && csv.includes('\"Channels\",\"Wrong ticket mode\"') && csv.includes('\"Channels\",\"Reply-route ready\"') && csv.includes('\"Channels\",\"Reply-route blocked\"') && csv.includes('\"Automation\",\"Human-loop proof ready\"') && csv.includes('\"Automation\",\"Human-loop proof blocked\"') && csv.includes('\"Channels\",\"Live target proof passed\"') && csv.includes('\"Email\",\"Sync proof passed\"') && csv.includes('\"Email\",\"Delivery proof passed\"') && csv.includes('\"Channels\",\"Attachment lifecycle proof passed\"') && csv.includes('\"Web chat\",\"Session proof missing\"') && csv.includes('\"Web chat\",\"Delivery proof missing\"'); })()" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "(() => { const link = document.querySelector('[data-support-report-download]'); if (!link) return false; const csv = decodeURIComponent(link.href); return csv.includes('\"Automation\",\"Channel autopilot ready\"') && csv.includes('\"Automation\",\"Channel autopilot blocked\"'); })()" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "(() => { const link = document.querySelector('[data-support-report-download]'); if (!link) return false; const csv = decodeURIComponent(link.href); return csv.includes('\"Knowledge\",\"Knowledge assist proof ready\"') && csv.includes('\"Knowledge\",\"Knowledge assist proof blocked\"') && csv.includes('\"Knowledge\",\"Successful knowledge assist runs\"'); })()" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "(() => { const link = document.querySelector('[data-support-report-download]'); if (!link) return false; const csv = decodeURIComponent(link.href); return csv.includes('\"Accounts\",\"Account intelligence proof ready\"') && csv.includes('\"Accounts\",\"Account intelligence proof blocked\"') && csv.includes('\"Accounts\",\"Account intelligence actions\"'); })()" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "(() => { const link = document.querySelector('[data-support-launch-proof-download]'); if (!link) return false; const json = decodeURIComponent(link.href); return link.getAttribute('download') === 'support-launch-proof-project1.json' && json.includes('\"kind\": \"support_launch_proof_bundle\"') && json.includes('\"projectId\": \"project1\"') && json.includes('\"launchProof\"') && json.includes('\"ticketCreation\"') && json.includes('\"replyRoute\"') && json.includes('\"channelAutopilot\"') && json.includes('\"knowledgeAssist\"') && json.includes('\"accountIntelligence\"') && json.includes('\"humanLoop\"') && json.includes('\"ticketWorkflow\"') && json.includes('\"runHistory\"') && json.includes('\"channels\"'); })()" --timeout-ms 15000 >/dev/null

cmux browser "$SURFACE" click "[data-run-launch-proof]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Latest proof run') && document.body.textContent.includes('SLA due-soon watch')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Latest proof run"
assert_text "SLA due-soon watch"
assert_text "Workflow lifecycle proof"
assert_text "0 failed"

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/automations" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Workflow rules') && document.body.textContent.includes('Run SLA scan')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('SLA breach escalation')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "SLA breach escalation"
assert_text "Run SLA scan"
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-automation-manual-issue]')) && Boolean(document.querySelector('[data-automation-conditions-json]')) && Boolean(document.querySelector('[data-automation-actions-json]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval '(() => {
  const set = (selector, value) => {
    const el = document.querySelector(selector);
    const proto = el.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  };
  set("[data-automation-manual-issue]", "issue-discord-open");
  set("[data-automation-conditions-json]", "{}");
  set("[data-automation-actions-json]", JSON.stringify([{
    type: "prepare_agent_reply",
    question: "Draft and auto-send only when policy allows it.",
    createDraft: true,
    approvalRequired: true,
    autoSend: true,
    includeFeedbackLink: true
  }], null, 2));
})()' >/dev/null
cmux browser "$SURFACE" click "[data-automation-preview-run]" >/dev/null
cmux browser "$SURFACE" wait --function "(() => { const preview = document.querySelector('[data-automation-preview]'); const warning = document.querySelector('[data-automation-preview-warning=\"auto_send_blocked\"]'); const action = document.querySelector('[data-automation-preview-action=\"prepare_agent_reply\"]'); return preview && warning && action && preview.textContent.includes('1 blocked auto-send') && warning.textContent.includes('Auto-send blocked') && action.textContent.includes('Agent auto-send blocked'); })()" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Auto-send blocked"
assert_text "1 blocked auto-send"
assert_text "Agent auto-send blocked"
cmux browser "$SURFACE" click "[data-run-sla-scan]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('SLA escalation result') && document.body.textContent.includes('issue-discord-open') && document.body.textContent.includes('escalated')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "SLA escalation result"
assert_text "issue-discord-open"
assert_text "1 escalated"
assert_text "1 automation"

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/inbox/issue-discord-open?view=board" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Discord incident: production API down')" --timeout-ms 15000 >/dev/null

cmux browser "$SURFACE" click "[data-ticket-review-package-approve-send]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('discord:reply:C123')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "(() => { const event = document.querySelector('[data-activity-event=\"event-reply-discord-1-sent\"]'); return event && event.textContent.includes('Reply sent') && event.textContent.includes('agent@example.com'); })()" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Reply sent"
assert_text "agent@example.com"
assert_text "Delivery proof"
assert_text "discord:reply:C123"
assert_text "Ready to close"
assert_text "Mark done"

cmux browser "$SURFACE" click "[data-ticket-next-action-mark-done]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('StatusDone')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "StatusDone"
assert_text "No immediate action"

cmux browser "$SURFACE" eval "(async () => { const res = await fetch('$API_URL/api/admin/projects/project1/issues/issue-discord-open/agent-answer', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ question: 'Find the best answer from the ticket context and knowledge base.', createDraft: false }) }); const data = await res.json(); if (!data.answer?.includes('Live agent answer from smoke')) throw new Error('agent answer proof missing'); if (!data.accountContext) throw new Error('agent account context missing'); if (!Array.isArray(data.citations) || data.citations.length === 0) throw new Error('agent citations missing'); document.body.setAttribute('data-agent-answer-proof', 'ready'); return data.answer; })()" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.getAttribute('data-agent-answer-proof') === 'ready'" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Queue if safe"

cmux browser "$SURFACE" eval "(async () => { const res = await fetch('$API_URL/api/admin/projects/project1/issues/issue-discord-open/agent-answer', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ question: 'Queue a safe customer update with no approval.', createDraft: true, includeFeedbackLink: true, approvalRequired: false, autoSend: true }) }); const data = await res.json(); if (data.autoSend !== true) throw new Error('agent auto-send proof missing'); if (data.approvalRequired !== false) throw new Error('agent auto-send approval flag wrong'); if (data.reply?.status !== 'queued') throw new Error('agent auto-send reply not queued'); document.body.setAttribute('data-agent-auto-send-proof', 'ready'); return data.reply.status; })()" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.getAttribute('data-agent-auto-send-proof') === 'ready'" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Queue if safe"

cmux browser "$SURFACE" click "[data-ticket-split-message='msg-discord-1']" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Split message')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-ticket-split-confirm]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Issue split from ticket')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Suggested duplicates')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "document.querySelector('[data-ticket-assignee-current]')?.getAttribute('data-ticket-assignee-current') === 'agent@example.com'" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Split: Discord incident: production API down"
assert_text "Issue split from ticket"
assert_text "Suggested duplicates"
assert_text "agent@example.com"
assert_text "split source"

cmux browser "$SURFACE" click "[data-ticket-duplicate-suggestion='issue-discord-open']" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Merge ticket')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-ticket-merge-confirm]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Tickets merged') && document.body.textContent.includes('incidentapisplit')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Tickets merged"
assert_text "3 tickets"
assert_text "incidentapisplit"
assert_text "Discord incident: production API down"

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/channels?channel=discord-main" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Channel setup') && document.body.textContent.includes('Advanced checks') && document.body.textContent.includes('Launch details')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval '(() => {
  for (const label of ["Advanced checks", "Launch details"]) {
    const button = Array.from(document.querySelectorAll("button")).find(el => el.textContent.includes(label));
    if (button) button.click();
  }
})()' >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('support-channel-lifecycle-smoke.sh')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Channel setup"
assert_text "Launch playbook"
assert_text "Run lifecycle smoke"
assert_text "SUPPORT_PROJECT_ID=project1 ADMIN_AUTH_TOKEN=<admin-api-token> ./support-channel-lifecycle-smoke.sh --channel-key discord-main --transport http"
assert_text "Channel webhook inbox"
assert_text "MESSAGE_DELIVERY"
assert_text "discord:reply:m-lost"
assert_text "unmatched"
assert_text "No outbound message matched this provider receipt."
cmux browser "$SURFACE" wait --function "(() => { const link = document.querySelector('[data-channel-activation-plan-download]'); if (!link) return false; const json = decodeURIComponent(link.href); return link.getAttribute('download') === 'support-channel-activation-plan-project1.json' && json.includes('\"kind\": \"support_channel_activation_plan\"') && json.includes('\"projectId\": \"project1\"') && json.includes('\"nextActions\"') && json.includes('\"secrets\"') && json.includes('\"surfaces\"') && json.includes('\"setupCommands\"') && json.includes('\"liveTargets\"'); })()" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-channel-webhook-retry='webhook-unmatched-receipt']" >/dev/null
cmux browser "$SURFACE" wait --function "(() => { const row = document.querySelector('[data-channel-webhook-event=\"webhook-unmatched-receipt\"]'); return row && row.textContent.includes('processed') && row.textContent.includes('Outbound: reply-discord-1') && row.textContent.includes('Ticket'); })()" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Receipt matched"
assert_text "processed"
assert_text "Outbound: reply-discord-1"
cmux browser "$SURFACE" click "[data-channel-smoke-command-copy]" >/dev/null

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/channels?channel=slack-main" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-channel-row=\"slack-main\"]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-channel-row='slack-main']" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Slack main')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('support-channel-lifecycle-smoke.sh')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Slack main"
assert_text "slack-main"
assert_text "SUPPORT_PROJECT_ID=project1 ADMIN_AUTH_TOKEN=<admin-api-token> ./support-channel-lifecycle-smoke.sh --channel-key slack-main --transport http"

cmux browser "$SURFACE" click "[data-channel-run-lifecycle-smoke]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('slack_bot') && document.body.textContent.includes('slack:reply:C777')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Lifecycle smoke sent"
assert_text "slack_bot"
assert_text "slack:reply:C777"

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/channels?channel=teams-main" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-channel-row=\"teams-main\"]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-channel-row='teams-main']" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Teams main')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('support-channel-lifecycle-smoke.sh')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Teams main"
assert_text "teams-main"
assert_text "SUPPORT_PROJECT_ID=project1 ADMIN_AUTH_TOKEN=<admin-api-token> ./support-channel-lifecycle-smoke.sh --channel-key teams-main --transport http"
assert_text "Run attachment lifecycle smoke"
assert_text "--channel-key teams-main --transport http --body \"\" --attachment"
assert_text "incident.txt"

cmux browser "$SURFACE" click "[data-channel-run-lifecycle-smoke]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('teams_graph') && document.body.textContent.includes('teams:reply:19:general@thread.tacv2')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Lifecycle smoke sent"
assert_text "teams_graph"
assert_text "teams:reply:19:general@thread.tacv2"

cmux browser "$SURFACE" click "#channel-lifecycle-attachment-only" >/dev/null
cmux browser "$SURFACE" wait --function "document.querySelector('#channel-lifecycle-attachment-only')?.getAttribute('aria-checked') === 'true'" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-channel-run-lifecycle-smoke]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('teams_graph') && document.body.textContent.includes('1 attachments') && document.body.textContent.includes('file-only')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Lifecycle smoke sent"
assert_text "teams_graph"
assert_text "1 attachments"
assert_text "file-only"
cmux browser "$SURFACE" click "#channel-lifecycle-attachment-only" >/dev/null
cmux browser "$SURFACE" wait --function "document.querySelector('#channel-lifecycle-attachment-only')?.getAttribute('aria-checked') === 'false'" --timeout-ms 15000 >/dev/null

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/channels?channel=telegram-main" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Telegram main')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('support-channel-lifecycle-smoke.sh')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Telegram main"
assert_text "telegram-main"
assert_text "SUPPORT_PROJECT_ID=project1 ADMIN_AUTH_TOKEN=<admin-api-token> ./support-channel-lifecycle-smoke.sh --channel-key telegram-main --transport http"

cmux browser "$SURFACE" click "[data-channel-run-lifecycle-smoke]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('telegram_bot') && document.body.textContent.includes('telegram:reply:chat-1')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Lifecycle smoke sent"
assert_text "telegram_bot"
assert_text "telegram:reply:chat-1"

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/channels?channel=web-main" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-channel-row=\"web-main\"]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-channel-row='web-main']" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('http://127.0.0.1:${API_PORT}/support/web-chat/project1?channel_key=web-main')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Web main"
assert_text "Web chat"
assert_text "$API_URL/support/web-chat/project1?channel_key=web-main"
assert_text "$API_URL/support/web-chat/project1/embed.js?channel_key=web-main"
assert_text "Prove visitor session"

cmux browser "$SURFACE" navigate "$API_URL/support/web-chat/project1?channel_key=web-main" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" eval "window.localStorage.clear(); window.location.reload();" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Support chat')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval "(() => { document.querySelector('#name').value = 'Web Visitor'; document.querySelector('#email').value = 'visitor@example.com'; document.querySelector('#body').value = 'Need help from web chat before rollout.'; document.querySelector('#send').click(); })()" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Ticket opened: issue-web-chat-smoke-1')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Ticket opened: issue-web-chat-smoke-1"
assert_text "Need help from web chat before rollout."

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/inbox/issue-web-chat-smoke-1?view=board" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Web chat from Web Visitor')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "8 tickets"
assert_text "Web chat from Web Visitor"
assert_text "web_chat"
assert_text "Website Visitors"
assert_text "1 reply draft"
assert_text "Thanks Web Visitor. We have your web chat ticket and are checking this now."

cmux browser "$SURFACE" click "[data-ticket-review-package-approve-send]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('web_chat_internal') && document.body.textContent.includes('web_chat:reply:web-session-smoke-1')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Reply sent"
assert_text "Delivery proof"
assert_text "web_chat_internal"
assert_text "web_chat:reply:web-session-smoke-1"

cmux browser "$SURFACE" navigate "$API_URL/support/web-chat/project1?channel_key=web-main" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Need help from web chat before rollout.') && document.body.textContent.includes('Thanks Web Visitor. We have your web chat ticket and are checking this now.')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval "(() => { document.querySelector('#body').value = 'Second web chat message should open another ticket but keep transcript.'; document.querySelector('#send').click(); })()" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Ticket opened: issue-web-chat-smoke-2') && document.body.textContent.includes('Need help from web chat before rollout.') && document.body.textContent.includes('Thanks Web Visitor. We have your web chat ticket and are checking this now.') && document.body.textContent.includes('Second web chat message should open another ticket but keep transcript.')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Ticket opened: issue-web-chat-smoke-2"
assert_text "Second web chat message should open another ticket but keep transcript."
assert_text "Thanks Web Visitor. We have your web chat ticket and are checking this now."

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/channels?channel=web-main" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Web chat sessions') && document.body.textContent.includes('2 tickets') && document.body.textContent.includes('3 messages') && Boolean(document.querySelector('[data-web-chat-session-ticket=\"issue-web-chat-smoke-1\"]')) && Boolean(document.querySelector('[data-web-chat-session-ticket=\"issue-web-chat-smoke-2\"]'))" --timeout-ms 15000 >/dev/null
capture_body
assert_text "2 tickets"
assert_text "3 messages"
assert_text "issue-web-chat-smoke-1"
assert_text "issue-web-chat-smoke-2"

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/channels?channel=whatsapp-main" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-channel-row=\"whatsapp-main\"]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-channel-row='whatsapp-main']" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('WhatsApp main')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('support-channel-lifecycle-smoke.sh')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "WhatsApp main"
assert_text "whatsapp-main"
assert_text "SUPPORT_PROJECT_ID=project1 ADMIN_AUTH_TOKEN=<admin-api-token> ./support-channel-lifecycle-smoke.sh --channel-key whatsapp-main --transport http"

cmux browser "$SURFACE" click "[data-channel-run-lifecycle-smoke]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('whatsapp') && document.body.textContent.includes('whatsapp:reply:4915112345678')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Lifecycle smoke sent"
assert_text "whatsapp"
assert_text "whatsapp:reply:4915112345678"

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/channels?channel=messenger-main" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-channel-row=\"messenger-main\"]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-channel-row='messenger-main']" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Messenger main')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('support-channel-lifecycle-smoke.sh')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Messenger main"
assert_text "messenger-main"
assert_text "SUPPORT_PROJECT_ID=project1 ADMIN_AUTH_TOKEN=<admin-api-token> ./support-channel-lifecycle-smoke.sh --channel-key messenger-main --transport http"

cmux browser "$SURFACE" click "[data-channel-run-lifecycle-smoke]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('messenger') && document.body.textContent.includes('messenger:reply:customer-psid-1')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Lifecycle smoke sent"
assert_text "messenger"
assert_text "messenger:reply:customer-psid-1"

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/channels?channel=sms-main" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-channel-row=\"sms-main\"]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-channel-row='sms-main']" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('SMS main')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('support-channel-lifecycle-smoke.sh')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "SMS main"
assert_text "sms-main"
assert_text "/api/internal/support/sms/sms-main"
assert_text "/api/internal/support/twilio/sms-main"
assert_text "SUPPORT_PROJECT_ID=project1 ADMIN_AUTH_TOKEN=<admin-api-token> ./support-channel-lifecycle-smoke.sh --channel-key sms-main --transport http"

cmux browser "$SURFACE" click "[data-channel-run-lifecycle-smoke]" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('twilio_sms') && document.body.textContent.includes('sms:reply:+14155550123')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Lifecycle smoke sent"
assert_text "twilio_sms"
assert_text "sms:reply:+14155550123"

cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/inbox?view=board" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-new-ticket-open]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" click "[data-new-ticket-open]" >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-new-ticket-email]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval "(() => { const set = (selector, value) => { const el = document.querySelector(selector); const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); }; set('[data-new-ticket-email]', 'manual.customer@example.test'); set('[data-new-ticket-name]', 'Manual Customer'); set('[data-new-ticket-account]', 'Manual Account'); set('[data-new-ticket-assignee]', 'agent@example.com'); set('[data-new-ticket-subject]', 'Manual smoke ticket'); set('[data-new-ticket-body]', 'Manual ticket lifecycle from cmux.'); })()" >/dev/null
cmux browser "$SURFACE" click "[data-new-ticket-create]" >/dev/null
cmux browser "$SURFACE" wait --function "!document.querySelector('[data-new-ticket-email]')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Message timeline') && document.body.textContent.includes('Manual smoke ticket') && document.body.textContent.includes('Manual ticket lifecycle from cmux.')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Manual smoke ticket"
assert_text "Manual ticket lifecycle from cmux."
assert_text "manual.customer@example.test"
assert_text "Manual Account"
assert_text "agent@example.com"

curl -fsS -X POST "$API_URL/api/admin/projects/project1/issues/issue-manual-smoke-1/replies" \
  -H "content-type: application/json" \
  --data '{"body":"Initial approval draft from smoke.","approvalRequired":true}' >/dev/null
cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/inbox/issue-manual-smoke-1?view=board" >/dev/null
cmux browser "$SURFACE" reload >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-outbound-reply-request-changes=\"reply-smoke-manual-1\"]')) && document.body.textContent.includes('Initial approval draft from smoke.')" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval "document.querySelector('[data-outbound-reply-request-changes=\"reply-smoke-manual-1\"]').click()" >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(document.querySelector('[data-outbound-change-note=\"reply-smoke-manual-1\"]'))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval "(() => { const el = document.querySelector('[data-outbound-change-note=\"reply-smoke-manual-1\"]'); const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set; setter.call(el, 'Add customer-safe next step and remove vague ETA.'); el.dispatchEvent(new Event('input', { bubbles: true })); })()" >/dev/null
cmux browser "$SURFACE" wait --function "document.querySelector('[data-outbound-change-note=\"reply-smoke-manual-1\"]')?.value === 'Add customer-safe next step and remove vague ETA.'" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval "document.querySelector('[data-outbound-change-submit=\"reply-smoke-manual-1\"]').click()" >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Changes requested') && document.body.textContent.includes('Add customer-safe next step and remove vague ETA.') && Boolean(document.querySelector('[data-outbound-reply-revise=\"reply-smoke-manual-1\"]'))" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Changes requested"
assert_text "Add customer-safe next step and remove vague ETA."
cmux browser "$SURFACE" eval "document.querySelector('[data-outbound-reply-revise=\"reply-smoke-manual-1\"]').click()" >/dev/null
cmux browser "$SURFACE" wait --function "Array.from(document.querySelectorAll('[data-outbound-reply]')).some((el) => el.textContent.includes('Revised draft from smoke: Add customer-safe next step and remove vague ETA.') && el.getAttribute('data-outbound-reply-status') === 'draft')" --timeout-ms 15000 >/dev/null
REVISED_REPLY_ID="$(cmux browser "$SURFACE" eval "Array.from(document.querySelectorAll('[data-outbound-reply]')).find((el) => el.textContent.includes('Revised draft from smoke: Add customer-safe next step and remove vague ETA.'))?.getAttribute('data-outbound-reply') || ''")"
if [ -z "$REVISED_REPLY_ID" ]; then
  echo "revised reply missing" >&2
  exit 1
fi
capture_body
assert_text "Revision prepared"
assert_text "Revised draft from smoke: Add customer-safe next step and remove vague ETA."
cmux browser "$SURFACE" eval "document.querySelector('[data-outbound-reply-action=\"approve-send\"][data-outbound-reply-id=\"$REVISED_REPLY_ID\"]').click()" >/dev/null
cmux browser "$SURFACE" wait --function "Array.from(document.querySelectorAll('[data-outbound-reply]')).some((el) => el.getAttribute('data-outbound-reply') === '$REVISED_REPLY_ID' && el.getAttribute('data-outbound-reply-status') === 'sent' && el.textContent.includes('Delivery proof') && el.textContent.includes('email:reply:manual.customer@example.test'))" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Delivery proof"
assert_text "email:reply:manual.customer@example.test"

curl -fsS -X POST "$API_URL/api/admin/projects/project1/issues/issue-manual-smoke-1/replies" \
  -H "content-type: application/json" \
  --data '{"body":"Retry smoke reply body.","status":"failed","error":"Simulated provider timeout"}' >/dev/null
cmux browser "$SURFACE" navigate "$ADMIN_URL/tenant1/project1/inbox/issue-manual-smoke-1?view=board" >/dev/null
cmux browser "$SURFACE" wait --load-state complete --timeout-ms 10000 >/dev/null
cmux browser "$SURFACE" wait --function "document.body.textContent.includes('Fix failed delivery') && document.body.textContent.includes('Simulated provider timeout') && Boolean(document.querySelector('[data-ticket-retry-failed]'))" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Fix failed delivery"
assert_text "Retry smoke reply body."
assert_text "Simulated provider timeout"
cmux browser "$SURFACE" click "[data-ticket-retry-failed]" >/dev/null
cmux browser "$SURFACE" wait --function "Array.from(document.querySelectorAll('[data-outbound-reply]')).some((el) => el.textContent.includes('Retry smoke reply body.') && el.getAttribute('data-outbound-reply-status') === 'sent' && el.textContent.includes('email:reply:manual.customer@example.test')) && document.body.textContent.includes('Reply sent')" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Retry smoke reply body."
assert_text "Reply sent"
assert_text "email:reply:manual.customer@example.test"
cmux browser "$SURFACE" wait --function "Boolean(Array.from(document.querySelectorAll('[data-kanban-lane=\"ongoing\"] [data-kanban-card]')).find((el) => el.textContent.includes('Manual smoke ticket')))" --timeout-ms 15000 >/dev/null
cmux browser "$SURFACE" eval '(() => {
  const card = Array.from(document.querySelectorAll(`[data-kanban-lane="ongoing"] [data-kanban-card]`)).find((el) => el.textContent.includes("Manual smoke ticket"));
  const lane = document.querySelector(`[data-kanban-lane="done"]`);
  if (!card || !lane) throw new Error("Manual ticket drag/drop target missing");
  const dataTransfer = new DataTransfer();
  card.dispatchEvent(new DragEvent("dragstart", { bubbles: true, cancelable: true, dataTransfer }));
  lane.dispatchEvent(new DragEvent("dragover", { bubbles: true, cancelable: true, dataTransfer }));
  lane.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer }));
  card.dispatchEvent(new DragEvent("dragend", { bubbles: true, cancelable: true, dataTransfer }));
})()' >/dev/null
cmux browser "$SURFACE" wait --function "Boolean(Array.from(document.querySelectorAll('[data-kanban-lane=\"done\"] [data-kanban-card]')).find((el) => el.textContent.includes('Manual smoke ticket') && el.getAttribute('data-kanban-card-status') === 'done'))" --timeout-ms 15000 >/dev/null
capture_body
assert_text "Manual smoke ticket"
assert_text "Done"

echo "cmux support inbox smoke: ok"
