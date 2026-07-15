/// <reference path="../pb_data/types.d.ts" />

/**
 * Durable inbound cursor state per support channel adapter.
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

            ensureCollection(app, {
                name: "support_channel_cursors",
                type: "base",
                fields: [
                    { name: "tenant",         type: "relation", required: false, collectionId: tenants.id,   maxSelect: 1, cascadeDelete: false },
                    { name: "project",        type: "relation", required: true,  collectionId: projects.id,  maxSelect: 1, cascadeDelete: true },
                    { name: "channel",        type: "relation", required: true,  collectionId: channels.id,  maxSelect: 1, cascadeDelete: true },
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
                    "CREATE UNIQUE INDEX idx_support_channel_cursors_channel_key ON support_channel_cursors (channel, cursor_key)",
                    "CREATE INDEX idx_support_channel_cursors_project_status ON support_channel_cursors (project, status, updated)",
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
            const col = app.findCollectionByNameOrId("support_channel_cursors");
            app.delete(col);
        } catch (_) {}
    },
);
