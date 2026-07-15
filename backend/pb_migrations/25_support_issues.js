/// <reference path="../pb_data/types.d.ts" />

/**
 * First-class support issue read model.
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
            let chats = null;
            try {
                chats = app.findCollectionByNameOrId("chats");
            } catch (_) {
                chats = null;
            }

            const fields = [
                { name: "tenant",            type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                { name: "project",           type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
            ];
            if (chats) {
                fields.push({ name: "chat", type: "relation", required: false, collectionId: chats.id, maxSelect: 1, cascadeDelete: false });
            }
            fields.push(
                { name: "source_email_id",   type: "text",     required: true },
                { name: "channel",           type: "text",     required: true },
                { name: "source",            type: "text",     required: false },
                { name: "status",            type: "text",     required: true },
                { name: "priority",          type: "text",     required: true },
                { name: "assignee_email",    type: "text",     required: false },
                { name: "account_name",      type: "text",     required: false },
                { name: "account_domain",    type: "text",     required: false },
                { name: "contact_email",     type: "text",     required: false },
                { name: "contact_name",      type: "text",     required: false },
                { name: "subject",           type: "text",     required: false },
                { name: "from_address",      type: "text",     required: false },
                { name: "ai_summary",        type: "editor",   required: false },
                { name: "activated_intent",  type: "text",     required: false },
                { name: "requires_human",    type: "bool",     required: false },
                { name: "message_count",     type: "number",   required: false },
                { name: "action_log",        type: "json",     required: false },
                { name: "latest_message_at", type: "date",     required: false },
                { name: "created",           type: "autodate", onCreate: true, onUpdate: false, required: false },
                { name: "updated",           type: "autodate", onCreate: true, onUpdate: true,  required: false },
            );

            ensureCollection(app, {
                name: "support_issues",
                type: "base",
                fields,
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_issues_project_source_email ON support_issues (project, source_email_id)",
                    "CREATE INDEX idx_support_issues_project_status_updated ON support_issues (project, status, updated)",
                    "CREATE INDEX idx_support_issues_tenant_updated ON support_issues (tenant, updated)",
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
            const col = app.findCollectionByNameOrId("support_issues");
            app.delete(col);
        } catch (_) {
            // Collection did not exist.
        }
    },
);
