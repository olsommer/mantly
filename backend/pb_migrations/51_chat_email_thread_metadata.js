/// <reference path="../pb_data/types.d.ts" />

/**
 * Preserve provider email thread metadata on analyzed chats.
 */

function hasField(collection, name) {
    return collection.fields.some((field) => field.name === name);
}

function addField(collection, field) {
    if (!hasField(collection, field.name)) {
        collection.fields.add(new Field(field));
    }
}

migrate(
    (app) => {
        try {
            const collection = app.findCollectionByNameOrId("chats");
            addField(collection, { name: "thread_id",  type: "text", required: false });
            addField(collection, { name: "message_id", type: "text", required: false });
            addField(collection, { name: "metadata",   type: "json", required: false });
            app.save(collection);
        } catch (_) {
            // Fresh sorted migration runs may execute before chats exists.
        }
    },
    (app) => {
        try {
            const collection = app.findCollectionByNameOrId("chats");
            for (const fieldName of ["thread_id", "message_id", "metadata"]) {
                try {
                    collection.fields.removeByName(fieldName);
                } catch (_) {}
            }
            app.save(collection);
        } catch (_) {}
    },
);
