/// <reference path="../pb_data/types.d.ts" />

/**
 * Durable issue action execution records for support workspace.
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
                name: "support_action_executions",
                type: "base",
                fields: [
                    { name: "tenant",       type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",      type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "issue",        type: "relation", required: true,  collectionId: issues.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "action_key",   type: "text",     required: true },
                    { name: "label",        type: "text",     required: true },
                    { name: "type",         type: "text",     required: false },
                    { name: "status",       type: "text",     required: true },
                    { name: "requested_by", type: "text",     required: false },
                    { name: "result",       type: "json",     required: false },
                    { name: "error",        type: "editor",   required: false },
                    { name: "metadata",     type: "json",     required: false },
                    { name: "started_at",   type: "date",     required: false },
                    { name: "completed_at", type: "date",     required: false },
                    { name: "created",      type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",      type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_support_action_exec_issue_created ON support_action_executions (issue, created)",
                    "CREATE INDEX idx_support_action_exec_project_status ON support_action_executions (project, status, updated)",
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
            const col = app.findCollectionByNameOrId("support_action_executions");
            app.delete(col);
        } catch (_) {}
    },
);
