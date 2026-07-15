/// <reference path="../pb_data/types.d.ts" />

/**
 * Channel webhook event inbox for delivery receipts and push channel events.
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
            const outbound = app.findCollectionByNameOrId("support_outbound_messages");

            ensureCollection(app, {
                name: "support_channel_webhook_events",
                type: "base",
                fields: [
                    { name: "tenant",              type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",             type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "channel",             type: "relation", required: true,  collectionId: channels.id, maxSelect: 1, cascadeDelete: true },
                    { name: "outbound_message",    type: "relation", required: false, collectionId: outbound.id, maxSelect: 1, cascadeDelete: false },
                    { name: "provider",            type: "text",     required: true },
                    { name: "event_id",            type: "text",     required: true },
                    { name: "event_type",          type: "text",     required: false },
                    { name: "provider_message_id", type: "text",     required: false },
                    { name: "status",              type: "text",     required: true },
                    { name: "error",               type: "editor",   required: false },
                    { name: "payload",             type: "json",     required: false },
                    { name: "result",              type: "json",     required: false },
                    { name: "received_at",         type: "date",     required: false },
                    { name: "processed_at",        type: "date",     required: false },
                    { name: "created",             type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",             type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_channel_webhook_events_channel_event ON support_channel_webhook_events (channel, event_id)",
                    "CREATE INDEX idx_support_channel_webhook_events_project_status ON support_channel_webhook_events (project, status, received_at)",
                    "CREATE INDEX idx_support_channel_webhook_events_provider_message ON support_channel_webhook_events (provider_message_id, received_at)",
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
            app.delete(app.findCollectionByNameOrId("support_channel_webhook_events"));
        } catch (_) {}
    },
);
