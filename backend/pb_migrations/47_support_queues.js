/// <reference path="../pb_data/types.d.ts" />

/**
 * Team queues for support ticket ownership before assignee claim.
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

function ensureField(collection, field) {
    if (!collection.fields.find(f => f.name === field.name)) {
        collection.fields.add(new Field(field));
    }
}

migrate(
    (app) => {
        try {
            const tenants = app.findCollectionByNameOrId("tenants");
            const projects = app.findCollectionByNameOrId("projects");

            const issues = app.findCollectionByNameOrId("support_issues");
            ensureField(issues, { name: "queue_key", type: "text", required: false });
            ensureField(issues, { name: "queue_name", type: "text", required: false });
            app.save(issues);

            ensureCollection(app, {
                name: "support_queues",
                type: "base",
                fields: [
                    { name: "tenant",                 type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",                type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "queue_key",              type: "text",     required: true },
                    { name: "name",                   type: "text",     required: true },
                    { name: "description",            type: "editor",   required: false },
                    { name: "default_assignee_email", type: "text",     required: false },
                    { name: "status",                 type: "text",     required: true },
                    { name: "metadata",               type: "json",     required: false },
                    { name: "created",                type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",                type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_queues_project_key ON support_queues (project, queue_key)",
                    "CREATE INDEX idx_support_queues_project_status_name ON support_queues (project, status, name)",
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
            app.delete(app.findCollectionByNameOrId("support_queues"));
        } catch (_) {}
        try {
            const issues = app.findCollectionByNameOrId("support_issues");
            for (const name of ["queue_key", "queue_name"]) {
                const field = issues.fields.find(f => f.name === name);
                if (field) {
                    issues.fields.removeById(field.id);
                }
            }
            app.save(issues);
        } catch (_) {}
    },
);
