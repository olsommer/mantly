/// <reference path="../pb_data/types.d.ts" />

/**
 * Ticket watchers for follow/mention collaboration signals.
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
                name: "support_issue_watchers",
                type: "base",
                fields: [
                    { name: "tenant",        type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",       type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "issue",         type: "relation", required: true,  collectionId: issues.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "watcher_email", type: "text",     required: true },
                    { name: "added_by",      type: "text",     required: false },
                    { name: "source",        type: "text",     required: false },
                    { name: "status",        type: "text",     required: true },
                    { name: "metadata",      type: "json",     required: false },
                    { name: "created",       type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",       type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_watchers_issue_email ON support_issue_watchers (issue, watcher_email)",
                    "CREATE INDEX idx_support_watchers_project_email_status ON support_issue_watchers (project, watcher_email, status)",
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
            app.delete(app.findCollectionByNameOrId("support_issue_watchers"));
        } catch (_) {}
    },
);
