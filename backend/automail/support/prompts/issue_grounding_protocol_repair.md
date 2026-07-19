## Required Protocol Correction

The previous grounding response was rejected as malformed. Correct the protocol;
do not copy its invalid identifiers.

Protocol errors:
{protocol_errors}

Invalid evidence IDs from the rejected response:
{invalid_evidence_ids}

Exact Allowed Evidence IDs:
{allowed_evidence_ids}

Exact Answer Unit IDs:
{answer_unit_ids}

Exact Answer Obligation IDs:
{answer_obligation_ids}

Return the complete structured grounding response again. Every `evidence_ids`
entry must exactly equal one item from Exact Allowed Evidence IDs. Object keys
and structural labels such as `runbookActions`, `context`, `concerns`, or
`toolEvidence` are not evidence IDs unless they appear verbatim in that list.
Assess every listed answer unit and answer obligation exactly once. If the
corrected response remains malformed, it will fail closed.
