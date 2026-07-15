/// <reference path="../pb_data/types.d.ts" />

/**
 * Mantly — feedback collection for like/dislike ratings.
 *
 * Stores structured user feedback on pipeline results: a rating (like/dislike),
 * which pipeline stages were affected, and optional free-text details.
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
        // Defensive: wrap in try/catch in case prerequisite collections
        // don't exist yet due to migration ordering.
        try {
            const tenants = app.findCollectionByNameOrId("tenants");
            const projects = app.findCollectionByNameOrId("projects");

            ensureCollection(app, {
                name: "feedback",
                type: "base",
                fields: [
                    { name: "chat_id",          type: "text",     required: true },
                    { name: "user_email",       type: "text",     required: true },
                    { name: "rating",           type: "text",     required: true },   // "like" | "dislike"
                    { name: "affected_stages",  type: "json",     required: false },  // string[]
                { name: "feedback_text",    type: "text",     required: false },
                { name: "intent_name",      type: "text",     required: false },
                { name: "tenant",           type: "relation", required: false, collectionId: tenants.id,   maxSelect: 1, cascadeDelete: false },
                { name: "project",          type: "relation", required: false, collectionId: projects.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "created",          type: "autodate", onCreate: true,  onUpdate: false, required: false },
                    { name: "updated",          type: "autodate", onCreate: true,  onUpdate: true,  required: false },
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
            const col = app.findCollectionByNameOrId("feedback");
            app.delete(col);
        } catch (_) {
            // Collection didn't exist — ignore
        }
    },
);
