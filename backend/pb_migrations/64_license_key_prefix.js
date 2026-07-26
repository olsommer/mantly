/// <reference path="../pb_data/types.d.ts" />

/** Store only a short display prefix alongside hashed license keys. */

function addFieldIfMissing(collection, def) {
    if (!collection.fields.find((field) => field.name === def.name)) {
        collection.fields.add(new Field(def));
    }
}

function removeFieldIfPresent(collection, name) {
    const field = collection.fields.find((candidate) => candidate.name === name);
    if (field) {
        collection.fields.removeById(field.id);
    }
}

migrate(
    (app) => {
        let licenses;
        try {
            licenses = app.findCollectionByNameOrId("licenses");
        } catch (_) {
            // Fresh installs create this collection in the Python bootstrap.
            return;
        }
        addFieldIfMissing(licenses, {
            name: "key_prefix",
            type: "text",
            required: false,
        });
        app.save(licenses);
    },
    (app) => {
        let licenses;
        try {
            licenses = app.findCollectionByNameOrId("licenses");
        } catch (_) {
            return;
        }
        removeFieldIfPresent(licenses, "key_prefix");
        app.save(licenses);
    },
);
