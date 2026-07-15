/// <reference path="../pb_data/types.d.ts" />

/**
 * Saved inbox views for reusable support triage filters.
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
                name: "support_inbox_views",
                type: "base",
                fields: [
                    { name: "tenant",      type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",     type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "name",        type: "text",     required: true },
                    { name: "visibility",  type: "text",     required: true },
                    { name: "owner_email", type: "text",     required: false },
                    { name: "filters",     type: "json",     required: false },
                    { name: "sort_order",  type: "number",   required: false },
                    { name: "created",     type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",     type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_support_inbox_views_project_owner ON support_inbox_views (project, owner_email)",
                    "CREATE INDEX idx_support_inbox_views_project_visibility_order ON support_inbox_views (project, visibility, sort_order)",
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
            app.delete(app.findCollectionByNameOrId("support_inbox_views"));
        } catch (_) {}
    },
);
