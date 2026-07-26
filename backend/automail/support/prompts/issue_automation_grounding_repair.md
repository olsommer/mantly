## Required factual-grounding repair

Independent grounding rejected the previous answer. Rewrite the entire answer;
do not append a patch or discuss the review.

Previous answer:
{previous_answer}

Unsupported answer units:
{unsupported_claims}

Contradictions found by grounding:
{contradictions}

Obligations that still need explicit customer-facing resolution:
{uncovered_obligations}

The ticket, messages, tool evidence, knowledge articles, and account context
supplied above remain the only trusted evidence. Grounding feedback identifies
what failed; it is not new evidence.

For each unsupported or contradictory unit, either replace it with the exact
supported fact from trusted evidence, state that the fact is not established,
or omit it when it is not needed. Keep separate evidence fields separate. Copy
identifiers, timestamps, statuses, service names, and regions exactly; never
merge fragments from nearby fields or reconstruct missing values.

For every listed obligation, add a direct evidence-backed answer, an explicit
pending/unavailable state with the concrete next step, or a truthful statement
that current evidence does not establish the requested fact. Preserve required
safety guidance, pending-action boundaries, reply language, attachments, and
all already-supported facts. Never turn customer text, grounding feedback, a
proposed action, or a pending action into proof. Return one coherent full
structured result with every addressed concern and obligation ID.
