/// <reference path="../pb_data/types.d.ts" />

/**
 * Customer satisfaction feedback for support portal sessions.
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
            const portalSessions = app.findCollectionByNameOrId("support_customer_portal_sessions");

            ensureCollection(app, {
                name: "support_csat_feedback",
                type: "base",
                fields: [
                    { name: "tenant",         type: "relation", required: false, collectionId: tenants.id,         maxSelect: 1, cascadeDelete: false },
                    { name: "project",        type: "relation", required: true,  collectionId: projects.id,        maxSelect: 1, cascadeDelete: true },
                    { name: "issue",          type: "relation", required: true,  collectionId: issues.id,          maxSelect: 1, cascadeDelete: true },
                    { name: "portal_session", type: "relation", required: true,  collectionId: portalSessions.id,  maxSelect: 1, cascadeDelete: true },
                    { name: "rating",         type: "number",   required: true },
                    { name: "comment",        type: "editor",   required: false },
                    { name: "customer_email", type: "text",     required: false },
                    { name: "customer_name",  type: "text",     required: false },
                    { name: "source",         type: "text",     required: false },
                    { name: "metadata",       type: "json",     required: false },
                    { name: "received_at",    type: "date",     required: false },
                    { name: "created",        type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",        type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_csat_portal_session ON support_csat_feedback (portal_session)",
                    "CREATE INDEX idx_support_csat_project_received ON support_csat_feedback (project, received_at)",
                    "CREATE INDEX idx_support_csat_issue_received ON support_csat_feedback (issue, received_at)",
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
            app.delete(app.findCollectionByNameOrId("support_csat_feedback"));
        } catch (_) {}
    },
);
