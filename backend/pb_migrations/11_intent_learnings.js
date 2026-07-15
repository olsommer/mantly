/// <reference path="../pb_data/types.d.ts" />

/**
 * Mantly — intent_learnings collection.
 *
 * Stores AI-generated learning rules derived from user feedback via the
 * reflect agent.  Each record is a single actionable rule scoped to a
 * specific intent (by name).  Admins can edit or delete individual
 * learnings from the admin UI, and toggle whether they are injected
 * into the response agent prompt.
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
        // Defensive: prerequisite collections may not exist yet when this runs
        // because PB sorts migrations lexicographically ("11_*" < "1_*").
        // The auto-generated 1776880206_created_intent_learnings.js already
        // creates the full collection, so this is a safe no-op in that case.
        try {
            const tenants = app.findCollectionByNameOrId("tenants");
            const projects = app.findCollectionByNameOrId("projects");

            ensureCollection(app, {
                name: "intent_learnings",
                type: "base",
                fields: [
                    { name: "intent_name",         type: "text",     required: true },
                    { name: "learning",            type: "text",     required: true },
                    { name: "source_feedback_id",  type: "text",     required: false },
                    { name: "tenant",              type: "relation", required: false, collectionId: tenants.id,   maxSelect: 1, cascadeDelete: false },
                    { name: "project",             type: "relation", required: false, collectionId: projects.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "created",             type: "autodate", onCreate: true,  onUpdate: false, required: false },
                    { name: "updated",             type: "autodate", onCreate: true,  onUpdate: true,  required: false },
                ],
                indexes: [],
                listRule:   null,
                viewRule:   null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });
        } catch (_) {
            // Prerequisites don't exist yet — auto-generated migration handles this
        }
    },

    // ── Revert ─────────────────────────────────────────────────────────────────
    (app) => {
        try {
            const col = app.findCollectionByNameOrId("intent_learnings");
            app.delete(col);
        } catch (_) {
            // Collection didn't exist — ignore
        }
    },
);
