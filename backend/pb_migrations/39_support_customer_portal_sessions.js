/// <reference path="../pb_data/types.d.ts" />

/**
 * Customer-facing support portal sessions.
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
                name: "support_customer_portal_sessions",
                type: "base",
                fields: [
                    { name: "tenant",           type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",          type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "issue",            type: "relation", required: true,  collectionId: issues.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "token_hash",       type: "text",     required: true },
                    { name: "status",           type: "text",     required: true },
                    { name: "expires_at",       type: "date",     required: false },
                    { name: "last_accessed_at", type: "date",     required: false },
                    { name: "created_by",       type: "text",     required: false },
                    { name: "metadata",         type: "json",     required: false },
                    { name: "created",          type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",          type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_portal_token_hash ON support_customer_portal_sessions (token_hash)",
                    "CREATE INDEX idx_support_portal_issue_status ON support_customer_portal_sessions (issue, status)",
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
            app.delete(app.findCollectionByNameOrId("support_customer_portal_sessions"));
        } catch (_) {}
    },
);
