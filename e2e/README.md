# Reusable E2E personas

This folder stores portable, machine-validated personas for realistic Mantly
end-to-end testing. A persona describes the operator's point of view, synthetic
knowledge, deterministic tool facts, semantic runbook expectations, customer
emails, and the outcomes that must be visible in the Inbox audit.

The built-in personas are:

| File | Perspective | Main coverage |
| --- | --- | --- |
| `personas/lawyer.yaml` | Swiss law-firm intake and operations | Confidential intake, conflicts, deadlines, legal knowledge, billing, documents, and scheduling |
| `personas/fulfillment.yaml` | E-commerce fulfillment operations | Shipment tools, warehouse actions, multi-concern messages, returns, SLAs, and damaged-battery safety |
| `personas/saas-support.yaml` | B2B SaaS support and security | Authorization, account security, privacy, billing, incidents, integrations, prompt injection, and destructive actions |

## Safety contract

Persona files never contain live tenant IDs, channel IDs, credentials, or auth
tokens. All knowledge and tool records are synthetic. A runner must seed them
only into an isolated QA tenant and derive fresh thread, message, and event IDs
from a unique run ID.

Every built-in persona defaults to:

- human approval for replies and mutating actions;
- zero external sends and zero automatic external actions;
- one integrated draft even when several concerns activate several runbooks;
- exact grounding and obligation-coverage checks;
- all nine processing stages visible in the audit;
- a replay of every original message ID with no state change.

Read-only lookup tools may return the fixture facts in each persona. Entries in
`pending_actions` are proposals only and must remain pending until explicitly
approved by a human tester.

## Runtime IDs

The stored inbound address and subject are stable templates. Before submission,
a runner should create a case token such as
`<persona-id>-<run-id>-<case-id-lower>` and use it to:

1. plus-address the `@example.test` sender;
2. suffix the subject;
3. create unique thread, message, and event IDs;
4. replay the same message and event IDs for the idempotency assertion.

Follow-ups use a new message ID and the original thread ID. They must update the
same ticket.

## Validate

From the repository root:

```sh
uv run --project backend python -m e2e.validate
(cd backend && uv run pytest tests/test_support_e2e_personas.py)
```

Validation is offline and does not create tickets or call an LLM.

## Run against live QA projects

The live runner requires one isolated QA project and email channel per persona.
Use fresh disposable projects with no automation rules. The API runtime must
temporarily set `ENABLE_E2E_FIXTURES=true`; disable it and redeploy after the
test so synthetic fixture resolution is unavailable during normal operation.
It reads the bearer token from an environment variable and never includes it in
logs or reports. `--seed` replaces the target project's draft runbook set with
the persona's exact runbooks, publishes reviewed synthetic knowledge, forces
human approval, disables auto-send, and removes outbound webhook configuration.

```sh
export MANTLY_E2E_BEARER_TOKEN='<platform or QA admin token>'
uv run --project backend python -m e2e.live \
  --api-base https://api.mantly.io \
  --target lawyer='<lawyer-project-id>:<email-channel-id>' \
  --target fulfillment='<fulfillment-project-id>:<email-channel-id>' \
  --target saas-support='<saas-project-id>:<email-channel-id>' \
  --seed \
  --report /tmp/mantly-e2e-report.json
```

The runner submits cases serially. For every original message it checks the
activated concern/runbook set, deterministic read-only fixture tools, one
approval-gated combined draft, grounding and obligation coverage, reviewed
knowledge citations, all nine progress stages, pending non-routable actions,
zero queued/sent replies, and an identical-message replay. It also verifies
same-thread follow-ups remain on one ticket and runs each persona's knowledge
agent check with `createDraft=false`.

Without `--seed`, the runner first verifies that all persona knowledge markers
already exist. Runtime project, channel, ticket, and article IDs are written
only to the requested report path; keep reports outside the repository.
