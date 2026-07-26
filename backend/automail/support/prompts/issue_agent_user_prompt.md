Inspect the isolated workspace and handle this agent request:

{question}

Runtime-extracted direct question checklist:

{request_items}

For every checklist entry, return exactly one `request_item_assessments` item.
Use its exact `id`. `answer_excerpt` must be an exact, non-empty, contiguous
excerpt from the final customer answer that answers that specific question or
states its specific unknown/unavailable result. Never use one generic review
sentence as proof for unrelated checklist items.

Search before answering. Return the required structured result when finished.
