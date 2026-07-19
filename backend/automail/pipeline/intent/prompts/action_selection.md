## Action Selection

Always return `selected_action_names` as an array. Include only exact configured action names that are materially applicable to this routed concern.

Return an empty array when no configured action should be proposed. Suppress actions when their prerequisites fail, the requester lacks sufficient authority, or the message only raises a hypothetical possibility. Never select an action as a precaution.
