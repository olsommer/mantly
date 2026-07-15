/// <reference path="../pb_data/types.d.ts" />

/**
 * Durable outbound support reply records.
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
                name: "support_outbound_messages",
                type: "base",
                fields: [
                    { name: "tenant",              type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",             type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "issue",               type: "relation", required: true,  collectionId: issues.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "channel",             type: "text",     required: true },
                    { name: "to_address",          type: "text",     required: true },
                    { name: "from_address",        type: "text",     required: false },
                    { name: "subject",             type: "text",     required: true },
                    { name: "body",                type: "editor",   required: true },
                    { name: "status",              type: "text",     required: true },
                    { name: "provider",            type: "text",     required: false },
                    { name: "provider_message_id", type: "text",     required: false },
                    { name: "error",               type: "editor",   required: false },
                    { name: "created_by",          type: "text",     required: false },
                    { name: "sent_at",             type: "date",     required: false },
                    { name: "metadata",            type: "json",     required: false },
                    { name: "created",             type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",             type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_support_outbound_issue_created ON support_outbound_messages (issue, created)",
                    "CREATE INDEX idx_support_outbound_project_status ON support_outbound_messages (project, status, updated)",
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
            const col = app.findCollectionByNameOrId("support_outbound_messages");
            app.delete(col);
        } catch (_) {}
    },
);
