/// <reference path="../pb_data/types.d.ts" />

/**
 * Active CRM connector config, cursors, and sync run audit.
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

            const connectors = ensureCollection(app, {
                name: "support_crm_connectors",
                type: "base",
                fields: [
                    { name: "tenant",        type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",       type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "connector_key", type: "text",     required: true },
                    { name: "provider",      type: "text",     required: true },
                    { name: "name",          type: "text",     required: true },
                    { name: "status",        type: "text",     required: false },
                    { name: "config",        type: "json",     required: false },
                    { name: "last_sync_at",  type: "date",     required: false },
                    { name: "created",       type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",       type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_crm_connectors_project_key ON support_crm_connectors (project, connector_key)",
                    "CREATE INDEX idx_support_crm_connectors_project_provider ON support_crm_connectors (project, provider)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });

            ensureCollection(app, {
                name: "support_crm_cursors",
                type: "base",
                fields: [
                    { name: "tenant",         type: "relation", required: false, collectionId: tenants.id,     maxSelect: 1, cascadeDelete: false },
                    { name: "project",        type: "relation", required: true,  collectionId: projects.id,    maxSelect: 1, cascadeDelete: true },
                    { name: "connector",      type: "relation", required: true,  collectionId: connectors.id,  maxSelect: 1, cascadeDelete: true },
                    { name: "cursor_key",     type: "text",     required: true },
                    { name: "cursor_value",   type: "text",     required: false },
                    { name: "status",         type: "text",     required: false },
                    { name: "last_error",     type: "editor",   required: false },
                    { name: "metadata",       type: "json",     required: false },
                    { name: "last_synced_at", type: "date",     required: false },
                    { name: "created",        type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",        type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_crm_cursors_connector_key ON support_crm_cursors (connector, cursor_key)",
                    "CREATE INDEX idx_support_crm_cursors_project_status ON support_crm_cursors (project, status, updated)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });

            ensureCollection(app, {
                name: "support_crm_sync_runs",
                type: "base",
                fields: [
                    { name: "tenant",       type: "relation", required: false, collectionId: tenants.id,    maxSelect: 1, cascadeDelete: false },
                    { name: "project",      type: "relation", required: true,  collectionId: projects.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "connector",    type: "relation", required: true,  collectionId: connectors.id, maxSelect: 1, cascadeDelete: true },
                    { name: "source",       type: "text",     required: false },
                    { name: "status",       type: "text",     required: false },
                    { name: "processed",    type: "number",   required: false },
                    { name: "failed",       type: "number",   required: false },
                    { name: "skipped",      type: "number",   required: false },
                    { name: "objects_seen", type: "number",   required: false },
                    { name: "error",        type: "editor",   required: false },
                    { name: "result",       type: "json",     required: false },
                    { name: "started_at",   type: "date",     required: false },
                    { name: "completed_at", type: "date",     required: false },
                    { name: "created",      type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",      type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_support_crm_sync_runs_connector_started ON support_crm_sync_runs (connector, started_at)",
                    "CREATE INDEX idx_support_crm_sync_runs_project_status ON support_crm_sync_runs (project, status, started_at)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });
        } catch (_) {
            // Prerequisites missing. Runtime bootstrap creates the collections.
        }
    },
    (app) => {
        for (const name of ["support_crm_sync_runs", "support_crm_cursors", "support_crm_connectors"]) {
            try {
                app.delete(app.findCollectionByNameOrId(name));
            } catch (_) {}
        }
    },
);
