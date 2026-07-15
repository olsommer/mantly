/// <reference path="../pb_data/types.d.ts" />

/**
 * Durable in-ticket agent chat transcript.
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
            const aiRuns = app.findCollectionByNameOrId("support_ai_runs");
            const outbound = app.findCollectionByNameOrId("support_outbound_messages");

            ensureCollection(app, {
                name: "support_agent_messages",
                type: "base",
                fields: [
                    { name: "tenant",       type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",      type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "issue",        type: "relation", required: true,  collectionId: issues.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "run",          type: "relation", required: false, collectionId: aiRuns.id,   maxSelect: 1, cascadeDelete: false },
                    { name: "reply",        type: "relation", required: false, collectionId: outbound.id, maxSelect: 1, cascadeDelete: false },
                    { name: "role",         type: "text",     required: true },
                    { name: "author_email", type: "text",     required: false },
                    { name: "body",         type: "editor",   required: true },
                    { name: "metadata",     type: "json",     required: false },
                    { name: "occurred_at",  type: "date",     required: false },
                    { name: "created",      type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",      type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_support_agent_messages_issue_created ON support_agent_messages (issue, created)",
                    "CREATE INDEX idx_support_agent_messages_project_created ON support_agent_messages (project, created)",
                    "CREATE INDEX idx_support_agent_messages_issue_role ON support_agent_messages (issue, role, created)",
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
            const col = app.findCollectionByNameOrId("support_agent_messages");
            app.delete(col);
        } catch (_) {}
    },
);
