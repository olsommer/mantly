/// <reference path="../pb_data/types.d.ts" />

/**
 * Mantly — customer-facing run history for Monitor.
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
                name: "monitor_runs",
                type: "base",
                fields: [
                    { name: "tenant",       type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",      type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "source",       type: "text",     required: true },
                    { name: "status",       type: "text",     required: true },
                    { name: "started_at",   type: "date",     required: false },
                    { name: "completed_at", type: "date",     required: false },
                    { name: "duration_ms",  type: "number",   required: false },
                    { name: "user_email",   type: "text",     required: false },
                    { name: "input",        type: "json",     required: false },
                    { name: "output",       type: "json",     required: false },
                    { name: "actions",      type: "json",     required: false },
                    { name: "error",        type: "text",     required: false },
                    { name: "created",      type: "autodate", onCreate: true,  onUpdate: false, required: false },
                    { name: "updated",      type: "autodate", onCreate: true,  onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_monitor_runs_project_created ON monitor_runs (project, created)",
                    "CREATE INDEX idx_monitor_runs_tenant_created ON monitor_runs (tenant, created)",
                ],
                listRule:   null,
                viewRule:   null,
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
            const col = app.findCollectionByNameOrId("monitor_runs");
            app.delete(col);
        } catch (_) {
            // Collection did not exist.
        }
    },
);
