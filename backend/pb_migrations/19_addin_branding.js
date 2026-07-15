/// <reference path="../pb_data/types.d.ts" />

/**
 * Store tenant-level add-in branding.
 */

migrate((app) => {
    try {
        const collection = app.findCollectionByNameOrId("tenants");
        const existing = collection.fields.find(f => f.name === "addin_primary_color");
        if (existing) return;

        collection.fields.add(new Field({
            name: "addin_primary_color",
            type: "text",
            required: false,
            system: false,
        }));
        app.save(collection);
    } catch (_) {
        // Fresh sorted migration runs may execute before tenants exists.
        // Runtime schema bootstrap creates this field later.
    }
}, (app) => {
    try {
        const collection = app.findCollectionByNameOrId("tenants");
        const field = collection.fields.find(f => f.name === "addin_primary_color");
        if (field) {
            collection.fields.removeById(field.id);
            app.save(collection);
        }
    } catch (_) {}
});
