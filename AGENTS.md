# AGENTS.md

## Server credentials

For SSH and Coolify API credentials, refer to `server-connection.md`.

## Browser automation

When using `agent-browser` or the `cmux` browser CLI, **never use vision or take/read screenshots**. Rely exclusively on DOM-based selectors, accessibility trees, and text content to interact with and inspect pages.

## UI Developement
Always use shadcn primitives wherever possible.
For more infos about shadcn, refer to `llms/shadcn.txt`

## Workflow language
When the user writes `noop`, analyze/evaluate only. Do not implement until the user explicitly gives the go.

## Quality checks
After every code edit, run backend Ruff + pytest and frontend TypeScript + ESLint checks before reporting done.

## Prompt files
Store runtime LLM prompt text in colocated `prompts/*.md` files whenever possible. Keep Python/TypeScript code for loading templates and injecting dynamic values only.

## Caveman mode

Terse like caveman. Technical substance exact. Only fluff die.
Drop: articles, filler (just/really/basically), pleasantries, hedging.
Fragments OK. Short synonyms. Code unchanged.
Pattern: [thing] [action] [reason]. [next step].
ACTIVE EVERY RESPONSE. No revert after many turns. No filler drift.
Code/commits/PRs: normal. Off: "stop caveman" / "normal mode".
