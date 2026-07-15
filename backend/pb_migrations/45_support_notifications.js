/// <reference path="../pb_data/types.d.ts" />

/**
 * Agent-facing notifications for assigned tickets and SLA escalations.
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
                name: "support_notifications",
                type: "base",
                fields: [
                    { name: "tenant",          type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",         type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "issue",           type: "relation", required: true,  collectionId: issues.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "recipient_email", type: "text",     required: true },
                    { name: "type",            type: "text",     required: true },
                    { name: "title",           type: "text",     required: true },
                    { name: "body",            type: "editor",   required: false },
                    { name: "status",          type: "text",     required: true },
                    { name: "metadata",        type: "json",     required: false },
                    { name: "read_at",         type: "date",     required: false },
                    { name: "created",         type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",         type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_support_notifications_recipient_status_created ON support_notifications (project, recipient_email, status, created)",
                    "CREATE INDEX idx_support_notifications_issue_recipient ON support_notifications (issue, recipient_email)",
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
            app.delete(app.findCollectionByNameOrId("support_notifications"));
        } catch (_) {}
    },
);
