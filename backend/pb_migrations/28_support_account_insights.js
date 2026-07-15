/// <reference path="../pb_data/types.d.ts" />

/**
 * Account intelligence records derived from support issues.
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
            const accounts = app.findCollectionByNameOrId("support_accounts");
            const issues = app.findCollectionByNameOrId("support_issues");

            ensureCollection(app, {
                name: "support_account_insights",
                type: "base",
                fields: [
                    { name: "tenant",       type: "relation", required: false, collectionId: tenants.id,   maxSelect: 1, cascadeDelete: false },
                    { name: "project",      type: "relation", required: true,  collectionId: projects.id,  maxSelect: 1, cascadeDelete: true },
                    { name: "account",      type: "relation", required: true,  collectionId: accounts.id,  maxSelect: 1, cascadeDelete: true },
                    { name: "source_issue", type: "relation", required: false, collectionId: issues.id,    maxSelect: 1, cascadeDelete: false },
                    { name: "insight_key",  type: "text",     required: true },
                    { name: "type",         type: "text",     required: true },
                    { name: "title",        type: "text",     required: true },
                    { name: "body",         type: "editor",   required: false },
                    { name: "severity",     type: "text",     required: false },
                    { name: "status",       type: "text",     required: false },
                    { name: "metadata",     type: "json",     required: false },
                    { name: "first_seen_at", type: "date",    required: false },
                    { name: "last_seen_at", type: "date",     required: false },
                    { name: "created",      type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",      type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_account_insights_account_key ON support_account_insights (account, insight_key)",
                    "CREATE INDEX idx_support_account_insights_project_type ON support_account_insights (project, type, status)",
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
            const col = app.findCollectionByNameOrId("support_account_insights");
            app.delete(col);
        } catch (_) {}
    },
);
