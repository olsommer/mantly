/// <reference path="../pb_data/types.d.ts" />

/**
 * Store warning-only prompt injection monitoring output on analyzed chats.
 */
migrate((app) => {
    try {
        const collection = app.findCollectionByNameOrId("chats");
        const exists = collection.fields.find(f => f.name === "prompt_injection_result");
        if (!exists) {
            collection.fields.add(new Field({
                name: "prompt_injection_result",
                type: "json",
                required: false,
                system: false,
            }));
        }
        return app.save(collection);
    } catch (_) {
        // Fresh PocketBase applies lexicographic filenames before 1_initial_schema.
        // Runtime schema bootstrap / initial schema creates this field later.
    }
}, (app) => {
    try {
        const collection = app.findCollectionByNameOrId("chats");
        const field = collection.fields.find(f => f.name === "prompt_injection_result");
        if (field) {
            collection.fields.removeById(field.id);
        }
        return app.save(collection);
    } catch (_) {}
});
