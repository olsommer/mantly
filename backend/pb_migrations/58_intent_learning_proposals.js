/// <reference path="../pb_data/types.d.ts" />

/** Controlled feedback-learning proposals. Active rules remain separate. */

migrate(
    (app) => {
        try {
            app.findCollectionByNameOrId("intent_learning_proposals");
            return;
        } catch (_) {}

        const tenants = app.findCollectionByNameOrId("tenants");
        const projects = app.findCollectionByNameOrId("projects");
        const collection = new Collection({
                name: "intent_learning_proposals",
                type: "base",
                fields: [
                    { name: "intent_name", type: "text", required: true },
                    { name: "operation", type: "text", required: true },
                    { name: "status", type: "text", required: true },
                    { name: "proposed_learning", type: "editor", required: false },
                    { name: "before_learning", type: "editor", required: false },
                    { name: "target_learning_id", type: "text", required: false },
                    { name: "source_feedback_id", type: "text", required: false },
                    { name: "affected_stages", type: "json", required: false },
                    { name: "base_learning_hash", type: "text", required: true },
                    { name: "proposal_hash", type: "text", required: true },
                    { name: "evaluated_proposal_hash", type: "text", required: false },
                    { name: "evaluated_base_hash", type: "text", required: false },
                    { name: "eval_summary", type: "json", required: false },
                    { name: "eval_case_ids", type: "json", required: false },
                    { name: "eval_case_hash", type: "text", required: false },
                    { name: "eval_policy_hash", type: "text", required: false },
                    { name: "eval_dimension", type: "text", required: false },
                    { name: "minimum_score", type: "number", required: false },
                    { name: "error", type: "editor", required: false },
                    { name: "rejection_reason", type: "editor", required: false },
                    { name: "created_by", type: "text", required: false },
                    { name: "evaluated_by", type: "text", required: false },
                    { name: "published_by", type: "text", required: false },
                    { name: "rejected_by", type: "text", required: false },
                    { name: "active_learning_id", type: "text", required: false },
                    { name: "runbook_id", type: "text", required: true },
                    { name: "runbook_updated", type: "text", required: true },
                    { name: "tenant", type: "relation", required: false, collectionId: tenants.id, maxSelect: 1, cascadeDelete: false },
                    { name: "project", type: "relation", required: true, collectionId: projects.id, maxSelect: 1, cascadeDelete: false },
                    { name: "eval_set", type: "text", required: false },
                    { name: "eval_run", type: "text", required: false },
                    { name: "evaluated_at", type: "date", required: false },
                    { name: "published_at", type: "date", required: false },
                    { name: "rejected_at", type: "date", required: false },
                    { name: "created", type: "autodate", onCreate: true, onUpdate: false },
                    { name: "updated", type: "autodate", onCreate: true, onUpdate: true },
                ],
                indexes: [
                    "CREATE INDEX idx_intent_learning_proposals_scope ON intent_learning_proposals (project, intent_name, status)",
                    "CREATE INDEX idx_intent_learning_proposals_feedback ON intent_learning_proposals (source_feedback_id)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
        });
        app.save(collection);
    },
    (app) => {
        try {
            app.delete(app.findCollectionByNameOrId("intent_learning_proposals"));
        } catch (_) {}
    },
);
