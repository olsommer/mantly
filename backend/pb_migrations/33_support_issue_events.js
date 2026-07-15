/// <reference path="../pb_data/types.d.ts" />

/**
 * Append-only issue activity events for support workspace audit trails.
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
                name: "support_issue_events",
                type: "base",
                fields: [
                    { name: "tenant",        type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",       type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "issue",         type: "relation", required: true,  collectionId: issues.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "event_type",    type: "text",     required: true },
                    { name: "actor_email",   type: "text",     required: false },
                    { name: "title",         type: "text",     required: false },
                    { name: "body",          type: "editor",   required: false },
                    { name: "from_status",   type: "text",     required: false },
                    { name: "to_status",     type: "text",     required: false },
                    { name: "from_priority", type: "text",     required: false },
                    { name: "to_priority",   type: "text",     required: false },
                    { name: "metadata",      type: "json",     required: false },
                    { name: "occurred_at",   type: "date",     required: false },
                    { name: "created",       type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",       type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_support_issue_events_issue_occurred ON support_issue_events (issue, occurred_at)",
                    "CREATE INDEX idx_support_issue_events_project_type ON support_issue_events (project, event_type, occurred_at)",
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
            const col = app.findCollectionByNameOrId("support_issue_events");
            app.delete(col);
        } catch (_) {}
    },
);
