/// <reference path="../pb_data/types.d.ts" />

/**
 * Mantly — Projects & RBAC schema.
 *
 * New collections:
 *   projects         — sub-tenant groupings (e.g. departments)
 *   project_members  — many-to-many user↔project with role (admin | editor | viewer)
 *
 * Field additions to existing collections are handled by the Python bootstrap
 * (pb_bootstrap.py) to avoid PocketBase migration API limitations with
 * modifying existing collection schemas.
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
    // ── Apply ──────────────────────────────────────────────────────────────────
    (app) => {
        const tenants = app.findCollectionByNameOrId("tenants");
        const users = app.findCollectionByNameOrId("users");

        // ── projects ──────────────────────────────────────────────────────────
        const projects = ensureCollection(app, {
            name: "projects",
            type: "base",
            fields: [
                { name: "name", type: "text", required: true },
                { name: "description", type: "text", required: false },
                {
                    name: "tenant",
                    type: "relation",
                    required: true,
                    collectionId: tenants.id,
                    maxSelect: 1,
                    cascadeDelete: true,
                },
                { name: "created", type: "autodate", onCreate: true, onUpdate: false, required: false },
                { name: "updated", type: "autodate", onCreate: true, onUpdate: true, required: false },
            ],
            listRule: null,
            viewRule: null,
            createRule: null,
            updateRule: null,
            deleteRule: null,
        });

        // ── project_members ───────────────────────────────────────────────────
        ensureCollection(app, {
            name: "project_members",
            type: "base",
            fields: [
                {
                    name: "user",
                    type: "relation",
                    required: true,
                    collectionId: users.id,
                    maxSelect: 1,
                    cascadeDelete: true,
                },
                {
                    name: "project",
                    type: "relation",
                    required: true,
                    collectionId: projects.id,
                    maxSelect: 1,
                    cascadeDelete: true,
                },
                { name: "role", type: "text", required: true },
                { name: "created", type: "autodate", onCreate: true, onUpdate: false, required: false },
                { name: "updated", type: "autodate", onCreate: true, onUpdate: true, required: false },
            ],
            indexes: [
                "CREATE UNIQUE INDEX idx_project_members_unique ON project_members (user, project)",
            ],
            listRule: null,
            viewRule: null,
            createRule: null,
            updateRule: null,
            deleteRule: null,
        });
    },

    // ── Revert ─────────────────────────────────────────────────────────────────
    (app) => {
        for (const name of ["project_members", "projects"]) {
            try {
                const col = app.findCollectionByNameOrId(name);
                app.delete(col);
            } catch (_) {
                // Collection didn't exist — ignore
            }
        }
    },
);
