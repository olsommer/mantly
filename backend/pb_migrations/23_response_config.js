/// <reference path="../pb_data/types.d.ts" />

/**
 * Move response drafting config from the old generate_response child action
 * into project_intents.response, then delete the old pseudo-action.
 */
migrate(
    (app) => {
        try {
            app.db()
                .newQuery(
                    "UPDATE project_intents " +
                    "SET response = (" +
                    "  SELECT json_object(" +
                    "    'enabled', 1," +
                    "    'auto', coalesce(json_extract(intent_actions.config, '$.auto'), 1)," +
                    "    'response_rules', json(coalesce(json_extract(intent_actions.config, '$.response_rules'), '[]'))," +
                    "    'attachments', json(coalesce(json_extract(intent_actions.config, '$.attachments'), '[]'))," +
                    "    'use_feedback_learnings', coalesce(json_extract(intent_actions.config, '$.use_feedback_learnings'), 1)" +
                    "  ) " +
                    "  FROM intent_actions " +
                    "  WHERE intent_actions.intent = project_intents.id " +
                    "  AND intent_actions.type = 'generate_response' " +
                    "  ORDER BY intent_actions.sort_order ASC " +
                    "  LIMIT 1" +
                    ") " +
                    "WHERE EXISTS (" +
                    "  SELECT 1 FROM intent_actions " +
                    "  WHERE intent_actions.intent = project_intents.id " +
                    "  AND intent_actions.type = 'generate_response'" +
                    ")"
                )
                .execute();

            app.db()
                .newQuery("DELETE FROM intent_actions WHERE type = 'generate_response'")
                .execute();
        } catch (_) {
            // Fresh sorted migration runs may execute before pipeline collections exist.
        }
    },
    (app) => {
        // No down migration. response is now the canonical config location.
    },
);
