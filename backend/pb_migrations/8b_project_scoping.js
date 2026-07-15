/// <reference path="../pb_data/types.d.ts" />

/**
 * Add project-scoping fields to existing collections, org_name to tenants,
 * and is_root to users.
 *
 * Replaces the auto-generated 1776807365_*.js migrations which used
 * hardcoded collection IDs that are not portable across PB instances.
 */

function addFieldIfMissing(app, collectionName, fieldDef) {
    try {
        const col = app.findCollectionByNameOrId(collectionName);
        if (col.fields.find(f => f.name === fieldDef.name)) return;
        col.fields.add(new Field(fieldDef));
        app.save(col);
    } catch (_) {
        // Collection doesn't exist yet — skip
    }
}

migrate(
    // ── Apply ──────────────────────────────────────────────────────────────────
    (app) => {
        // Resolve projects collection ID dynamically
        let projectsId;
        try {
            const projects = app.findCollectionByNameOrId("projects");
            projectsId = projects.id;
        } catch (_) {
            // projects collection doesn't exist — skip all relation additions
            return;
        }

        const projectRelation = {
            type: "relation",
            required: false,
            collectionId: projectsId,
            maxSelect: 1,
            cascadeDelete: false,
        };

        // Add project relation to collections that need per-project scoping
        const collections = ["chats", "eval_runs", "eval_sets"];
        for (const name of collections) {
            addFieldIfMissing(app, name, { name: "project", ...projectRelation });
        }

        // Add org_name to tenants
        addFieldIfMissing(app, "tenants", {
            name: "org_name",
            type: "text",
            required: false,
        });

        // Add is_root to users
        addFieldIfMissing(app, "_pb_users_auth_", {
            name: "is_root",
            type: "bool",
            required: false,
        });
    },

    // ── Revert ─────────────────────────────────────────────────────────────────
    (app) => {
        const collections = ["chats", "eval_runs", "eval_sets"];
        for (const name of collections) {
            try {
                const col = app.findCollectionByNameOrId(name);
                const field = col.fields.find(f => f.name === "project");
                if (field) {
                    col.fields.removeById(field.id);
                    app.save(col);
                }
            } catch (_) { /* ignore */ }
        }

        try {
            const tenants = app.findCollectionByNameOrId("tenants");
            const orgField = tenants.fields.find(f => f.name === "org_name");
            if (orgField) {
                tenants.fields.removeById(orgField.id);
                app.save(tenants);
            }
        } catch (_) { /* ignore */ }

        try {
            const users = app.findCollectionByNameOrId("_pb_users_auth_");
            const rootField = users.fields.find(f => f.name === "is_root");
            if (rootField) {
                users.fields.removeById(rootField.id);
                app.save(users);
            }
        } catch (_) { /* ignore */ }
    },
);
