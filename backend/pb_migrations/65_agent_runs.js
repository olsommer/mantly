/// <reference path="../pb_data/types.d.ts" />

/** Canonical tenant-scoped billing ledger for inbound agent runs. */

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
                name: "agent_runs",
                type: "base",
                fields: [
                    { name: "tenant", type: "relation", required: true, collectionId: tenants.id, maxSelect: 1, cascadeDelete: true },
                    { name: "project", type: "relation", required: false, collectionId: projects.id, maxSelect: 1, cascadeDelete: false },
                    { name: "source", type: "text", required: true },
                    { name: "idempotency_key", type: "text", required: true },
                    { name: "created", type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated", type: "autodate", onCreate: true, onUpdate: true, required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_agent_runs_tenant_key ON agent_runs (tenant, idempotency_key)",
                    "CREATE INDEX idx_agent_runs_tenant_created ON agent_runs (tenant, created)",
                    "CREATE INDEX idx_agent_runs_project_created ON agent_runs (project, created)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });
        } catch (_) {
            // Runtime bootstrap creates the collection if prerequisites were absent.
        }
    },
    (app) => {
        try {
            const col = app.findCollectionByNameOrId("agent_runs");
            app.delete(col);
        } catch (_) {}
    },
);
