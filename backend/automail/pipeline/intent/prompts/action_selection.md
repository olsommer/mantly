## Action Selection

Always return `selected_action_names` as an array. Include only exact configured action names that are materially applicable to this routed concern.

Return an empty array when no configured action should be proposed. Suppress actions when their prerequisites fail, the requester lacks sufficient authority, or the message only raises a hypothetical possibility. Never select an action as a precaution.

Requester authority applies only to actions performed on the requester's behalf or actions that change customer state. It does not block an internal defensive or review action, such as opening a security or safety incident, fraud review, or escalation, when the routed concern itself provides the configured trigger. Select that internal action when materially applicable; it remains pending human approval and is not proof that any action ran.
