## Expected Outcomes
```json
{expected_json}
```

## Actual Pipeline Output
```json
{actual_json}
```

## Dimensions to Score

**Identity**: Did the pipeline correctly identify the customer?
Compare expected_customer_found and expected_customer_data against the actual identity_result.

**Intent**: Did the pipeline match the correct intent?
Compare expected_intent_matched and expected_intent_name against the actual intent_result.

**Actions**: Did the pipeline produce the correct actions/field values?
Compare expected_actions against the actual intent_result.actions.
Also check expected_requires_human against actual agent_response.requires_human.

{response_dimension}

Respond with this exact JSON structure (no markdown fences):
{{
{response_schema}
}}
