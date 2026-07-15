/// <reference path="../pb_data/types.d.ts" />

/**
 * Public web chat sessions linked to Inbox issues.
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
            const channels = app.findCollectionByNameOrId("support_channels");
            const issues = app.findCollectionByNameOrId("support_issues");

            ensureCollection(app, {
                name: "support_web_chat_sessions",
                type: "base",
                fields: [
                    { name: "tenant",          type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",         type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "channel",         type: "relation", required: true,  collectionId: channels.id, maxSelect: 1, cascadeDelete: true },
                    { name: "issue",           type: "relation", required: true,  collectionId: issues.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "session_key",     type: "text",     required: true },
                    { name: "visitor_id",      type: "text",     required: false },
                    { name: "visitor_email",   type: "text",     required: false },
                    { name: "visitor_name",    type: "text",     required: false },
                    { name: "page_url",        type: "text",     required: false },
                    { name: "status",          type: "text",     required: true },
                    { name: "metadata",        type: "json",     required: false },
                    { name: "last_message_at", type: "date",     required: false },
                    { name: "created",         type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",         type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_web_chat_sessions_key ON support_web_chat_sessions (session_key)",
                    "CREATE INDEX idx_support_web_chat_sessions_project_status ON support_web_chat_sessions (project, status, last_message_at)",
                    "CREATE INDEX idx_support_web_chat_sessions_channel_updated ON support_web_chat_sessions (channel, updated)",
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
            app.delete(app.findCollectionByNameOrId("support_web_chat_sessions"));
        } catch (_) {}
    },
);
