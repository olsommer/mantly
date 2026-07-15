/// <reference path="../pb_data/types.d.ts" />

/**
 * Project-scoped canned replies for Inbox agents.
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
                name: "support_reply_macros",
                type: "base",
                fields: [
                    { name: "tenant",      type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",     type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "title",       type: "text",     required: true },
                    { name: "body",        type: "editor",   required: false },
                    { name: "visibility",  type: "text",     required: true },
                    { name: "owner_email", type: "text",     required: false },
                    { name: "status",      type: "text",     required: true },
                    { name: "tags",        type: "json",     required: false },
                    { name: "metadata",    type: "json",     required: false },
                    { name: "created",     type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",     type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_support_reply_macros_project_status_title ON support_reply_macros (project, status, title)",
                    "CREATE INDEX idx_support_reply_macros_project_owner ON support_reply_macros (project, owner_email)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });
        } catch (_) {
            // Runtime bootstrap creates the collection when prerequisites are absent.
        }
    },
    (app) => {
        try {
            app.delete(app.findCollectionByNameOrId("support_reply_macros"));
        } catch (_) {}
    },
);
