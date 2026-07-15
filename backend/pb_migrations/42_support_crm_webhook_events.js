/// <reference path="../pb_data/types.d.ts" />

/**
 * CRM webhook event inbox for push sync.
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
            const connectors = app.findCollectionByNameOrId("support_crm_connectors");

            ensureCollection(app, {
                name: "support_crm_webhook_events",
                type: "base",
                fields: [
                    { name: "tenant",       type: "relation", required: false, collectionId: tenants.id,    maxSelect: 1, cascadeDelete: false },
                    { name: "project",      type: "relation", required: true,  collectionId: projects.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "connector",    type: "relation", required: true,  collectionId: connectors.id, maxSelect: 1, cascadeDelete: true },
                    { name: "provider",     type: "text",     required: true },
                    { name: "event_id",     type: "text",     required: true },
                    { name: "event_type",   type: "text",     required: false },
                    { name: "object_type",  type: "text",     required: false },
                    { name: "external_id",  type: "text",     required: false },
                    { name: "status",       type: "text",     required: true },
                    { name: "error",        type: "editor",   required: false },
                    { name: "payload",      type: "json",     required: false },
                    { name: "result",       type: "json",     required: false },
                    { name: "received_at",  type: "date",     required: false },
                    { name: "processed_at", type: "date",     required: false },
                    { name: "created",      type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",      type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_crm_webhook_events_connector_event ON support_crm_webhook_events (connector, event_id)",
                    "CREATE INDEX idx_support_crm_webhook_events_project_status ON support_crm_webhook_events (project, status, received_at)",
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
            app.delete(app.findCollectionByNameOrId("support_crm_webhook_events"));
        } catch (_) {}
    },
);
