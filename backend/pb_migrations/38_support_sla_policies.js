/// <reference path="../pb_data/types.d.ts" />

/**
 * Project-level support SLA policy settings.
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
                name: "support_sla_policies",
                type: "base",
                fields: [
                    { name: "tenant",                 type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",                type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "name",                   type: "text",     required: true },
                    { name: "active",                 type: "bool",     required: false },
                    { name: "first_response_minutes", type: "number",   required: false },
                    { name: "resolution_minutes",     type: "number",   required: false },
                    { name: "business_hours",         type: "json",     required: false },
                    { name: "metadata",               type: "json",     required: false },
                    { name: "created",                type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",                type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_support_sla_policies_project_active ON support_sla_policies (project, active)",
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
            app.delete(app.findCollectionByNameOrId("support_sla_policies"));
        } catch (_) {}
    },
);
