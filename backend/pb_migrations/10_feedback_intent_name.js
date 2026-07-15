/// <reference path="../pb_data/types.d.ts" />

/**
 * Add intent_name field to the feedback collection.
 *
 * Stores the intent that was active when feedback was given, so feedback can
 * be scoped per-intent when injected into future agent prompts.
 */

migrate(
    // ── Apply ──────────────────────────────────────────────────────────────────
    (app) => {
        // Defensive: the feedback collection may not exist yet when this runs
        // because PB sorts migrations lexicographically ("10_*" < "9_*").
        // The auto-generated 1776880206_created_feedback.js already includes
        // the intent_name field, so this is a safe no-op in that case.
        try {
            const feedback = app.findCollectionByNameOrId("feedback");

            // Only add if not already present
            if (!feedback.fields.find(f => f.name === "intent_name")) {
                feedback.fields.add(
                    new Field({ name: "intent_name", type: "text", required: false }),
                );
                app.save(feedback);
            }
        } catch (_) {
            // feedback collection will be created later with intent_name included
        }
    },

    // ── Revert ─────────────────────────────────────────────────────────────────
    (app) => {
        try {
            const feedback = app.findCollectionByNameOrId("feedback");
            const field = feedback.fields.find(f => f.name === "intent_name");
            if (field) {
                feedback.fields.remove(field);
                app.save(feedback);
            }
        } catch (_) {
            // Collection doesn't exist — nothing to revert
        }
    },
);
