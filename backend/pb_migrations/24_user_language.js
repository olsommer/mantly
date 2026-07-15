/// <reference path="../pb_data/types.d.ts" />

/**
 * Store each user's preferred UI language.
 */
migrate(
    (app) => {
        try {
            const collection = app.findCollectionByNameOrId("users");
            if (!collection.fields.find(f => f.name === "language")) {
                collection.fields.add(new Field({
                    name: "language",
                    type: "text",
                    required: false,
                    system: false,
                }));
            }
            return app.save(collection);
        } catch (_) {
            // Fresh sorted migration runs may execute before users is ready.
            // Runtime schema bootstrap creates this field later.
        }
    },
    (app) => {
        try {
            const collection = app.findCollectionByNameOrId("users");
            const field = collection.fields.find(f => f.name === "language");
            if (field) {
                collection.fields.removeById(field.id);
            }
            return app.save(collection);
        } catch (_) {}
    },
);
