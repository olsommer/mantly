/// <reference path="../pb_data/types.d.ts" />

/**
 * Issue-derived knowledge gap records for support knowledge workflows.
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
                name: "support_knowledge_gaps",
                type: "base",
                fields: [
                    { name: "tenant",                  type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",                 type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "issue",                   type: "relation", required: true,  collectionId: issues.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "gap_key",                 type: "text",     required: true },
                    { name: "title",                   type: "text",     required: true },
                    { name: "evidence",                type: "editor",   required: false },
                    { name: "status",                  type: "text",     required: false },
                    { name: "severity",                type: "text",     required: false },
                    { name: "suggested_article_title", type: "text",     required: false },
                    { name: "metadata",                type: "json",     required: false },
                    { name: "first_seen_at",           type: "date",     required: false },
                    { name: "last_seen_at",            type: "date",     required: false },
                    { name: "created",                 type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",                 type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_knowledge_gaps_project_key ON support_knowledge_gaps (project, gap_key)",
                    "CREATE INDEX idx_support_knowledge_gaps_project_status ON support_knowledge_gaps (project, status, updated)",
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
            const col = app.findCollectionByNameOrId("support_knowledge_gaps");
            app.delete(col);
        } catch (_) {}
    },
);
