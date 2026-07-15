/// <reference path="../pb_data/types.d.ts" />

/**
 * Mantly — add default_project field to users.
 *
 * Each user can have a default project that the addin /api/process endpoint
 * uses to scope the pipeline (intents, tools, config) when no explicit
 * project is provided in the request.
 */

migrate(
    // ── Apply ──────────────────────────────────────────────────────────────────
    (app) => {
        // Defensive: prerequisite collections may not exist yet when this runs
        // because PB sorts migrations lexicographically ("12_*" < "1_*").
        // The auto-generated 1776889980_updated_users.js already adds the
        // default_project field, so this is a safe no-op in that case.
        try {
            const users = app.findCollectionByNameOrId("users");
            const projects = app.findCollectionByNameOrId("projects");

            // Check if field already exists
            const existing = users.fields.find(f => f.name === "default_project");
            if (existing) return;

            users.fields.add(
                new Field({
                    name: "default_project",
                    type: "relation",
                    required: false,
                    collectionId: projects.id,
                    maxSelect: 1,
                    cascadeDelete: false,
                }),
            );

            app.save(users);
        } catch (_) {
            // Prerequisites don't exist yet — auto-generated migration handles this
        }
    },

    // ── Revert ─────────────────────────────────────────────────────────────────
    (app) => {
        try {
            const users = app.findCollectionByNameOrId("users");
            const field = users.fields.find(f => f.name === "default_project");
            if (field) {
                users.fields.removeById(field.id);
                app.save(users);
            }
        } catch (_) {
            // Collection doesn't exist — nothing to revert
        }
    },
);
