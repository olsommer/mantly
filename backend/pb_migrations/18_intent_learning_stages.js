/// <reference path="../pb_data/types.d.ts" />

/**
 * Store the feedback stages that produced an intent learning.
 */

migrate((app) => {
    try {
        const collection = app.findCollectionByNameOrId("intent_learnings");
        const existing = collection.fields.find(f => f.name === "affected_stages");
        if (existing) return;

        collection.fields.add(new Field({
            name: "affected_stages",
            type: "json",
            required: false,
            system: false,
        }));
        app.save(collection);
    } catch (_) {
        // Collection may not exist yet in fresh sorted migration runs.
    }
}, (app) => {
    try {
        const collection = app.findCollectionByNameOrId("intent_learnings");
        const field = collection.fields.find(f => f.name === "affected_stages");
        if (field) {
            collection.fields.removeById(field.id);
            app.save(collection);
        }
    } catch (_) {
        // Collection doesn't exist; ignore.
    }
});
