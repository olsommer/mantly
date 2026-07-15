/// <reference path="../pb_data/types.d.ts" />

/**
 * Store scheduled Stripe subscription cancellation state on tenants.
 */
migrate(
    (app) => {
        try {
            const collection = app.findCollectionByNameOrId("tenants");
            if (!collection.fields.find(f => f.name === "cancel_at_period_end")) {
                collection.fields.add(new Field({
                    name: "cancel_at_period_end",
                    type: "bool",
                    required: false,
                    system: false,
                }));
            }
            return app.save(collection);
        } catch (_) {
            // Fresh sorted migration runs may execute before tenants exists.
            // Runtime schema bootstrap creates this field later.
        }
    },
    (app) => {
        try {
            const collection = app.findCollectionByNameOrId("tenants");
            const field = collection.fields.find(f => f.name === "cancel_at_period_end");
            if (field) {
                collection.fields.removeById(field.id);
            }
            return app.save(collection);
        } catch (_) {}
    },
);
