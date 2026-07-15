/// <reference path="../pb_data/types.d.ts" />

/**
 * Outbound delivery run history for scheduler/admin observability.
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

            ensureCollection(app, {
                name: "support_delivery_runs",
                type: "base",
                fields: [
                    { name: "tenant",       type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",      type: "relation", required: false, collectionId: projects.id, maxSelect: 1, cascadeDelete: false },
                    { name: "source",       type: "text",     required: false },
                    { name: "status",       type: "text",     required: false },
                    { name: "processed",    type: "number",   required: false },
                    { name: "sent",         type: "number",   required: false },
                    { name: "failed",       type: "number",   required: false },
                    { name: "error",        type: "editor",   required: false },
                    { name: "result",       type: "json",     required: false },
                    { name: "started_at",   type: "date",     required: false },
                    { name: "completed_at", type: "date",     required: false },
                    { name: "created",      type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",      type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_support_delivery_runs_project_started ON support_delivery_runs (project, started_at)",
                    "CREATE INDEX idx_support_delivery_runs_status_started ON support_delivery_runs (status, started_at)",
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
            const col = app.findCollectionByNameOrId("support_delivery_runs");
            app.delete(col);
        } catch (_) {}
    },
);
