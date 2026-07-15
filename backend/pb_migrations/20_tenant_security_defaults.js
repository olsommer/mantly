/// <reference path="../pb_data/types.d.ts" />

/**
 * Store tenant-level security monitoring defaults.
 */

migrate((app) => {
    try {
        const collection = app.findCollectionByNameOrId("tenants");
        const newFields = [
            {
                name: "phishing_monitoring_enabled",
                type: "bool",
                required: false,
                system: false,
            },
            {
                name: "prompt_injection_monitoring_enabled",
                type: "bool",
                required: false,
                system: false,
            },
        ];

        const existingNames = new Set(collection.fields.map(f => f.name));
        for (const field of newFields) {
            if (!existingNames.has(field.name)) {
                collection.fields.add(new Field(field));
            }
        }

        return app.save(collection);
    } catch (_) {
        // Fresh sorted migration runs may execute before tenants exists.
        // Runtime schema bootstrap creates these fields later.
    }
}, (app) => {
    try {
        const collection = app.findCollectionByNameOrId("tenants");
        for (const name of ["phishing_monitoring_enabled", "prompt_injection_monitoring_enabled"]) {
            const field = collection.fields.find(f => f.name === name);
            if (field) {
                collection.fields.removeById(field.id);
            }
        }

        return app.save(collection);
    } catch (_) {}
});
