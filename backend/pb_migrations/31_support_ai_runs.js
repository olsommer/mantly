/// <reference path="../pb_data/types.d.ts" />

/**
 * Issue-linked AI run records for support workspace auditability.
 */

function ensureCollection(app, def) {
    try {
        return app.findCollectionByNameOrId(def.name);
    } catch (_) {
        const col = new Collection(def);
        app.save(col);
        return col;
    }
}

migrate(
    (app) => {
        try {
            const tenants = app.findCollectionByNameOrId("tenants");
            const projects = app.findCollectionByNameOrId("projects");
            const issues = app.findCollectionByNameOrId("support_issues");

            ensureCollection(app, {
                name: "support_ai_runs",
                type: "base",
                fields: [
                    { name: "tenant",          type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",         type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "issue",           type: "relation", required: true,  collectionId: issues.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "run_key",         type: "text",     required: true },
                    { name: "source",          type: "text",     required: false },
                    { name: "status",          type: "text",     required: true },
                    { name: "activated_intent", type: "text",    required: false },
                    { name: "requires_human",  type: "bool",     required: false },
                    { name: "summary",         type: "editor",   required: false },
                    { name: "identity_result", type: "json",     required: false },
                    { name: "intent_result",   type: "json",     required: false },
                    { name: "security_result", type: "json",     required: false },
                    { name: "token_usage",     type: "json",     required: false },
                    { name: "tool_calls",      type: "json",     required: false },
                    { name: "metadata",        type: "json",     required: false },
                    { name: "started_at",      type: "date",     required: false },
                    { name: "completed_at",    type: "date",     required: false },
                    { name: "created",         type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",         type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_ai_runs_issue_key ON support_ai_runs (issue, run_key)",
                    "CREATE INDEX idx_support_ai_runs_project_updated ON support_ai_runs (project, updated)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });
        } catch (_) {
            // Prerequisites missing. Runtime bootstrap creates the collection.
        }
    },
    (app) => {
        try {
            const col = app.findCollectionByNameOrId("support_ai_runs");
            app.delete(col);
        } catch (_) {}
    },
);
