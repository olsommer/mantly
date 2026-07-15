/// <reference path="../pb_data/types.d.ts" />

/**
 * Add billing / subscription fields to the tenants collection.
 *
 * Fields added:
 *   stripe_customer_id    — Stripe Customer ID (cus_xxx)
 *   subscription_id       — Stripe Subscription ID (sub_xxx)
 *   subscription_status   — none | active | past_due | canceled
 *   plan                  — free | pro
 *   current_period_start  — start of the current billing cycle (date)
 *   current_period_end    — end of the current billing cycle (date)
 */
migrate((app) => {
    const collection = app.findCollectionByNameOrId("tenants");

    const newFields = [
        {
            name: "stripe_customer_id",
            type: "text",
            required: false,
            system: false,
        },
        {
            name: "subscription_id",
            type: "text",
            required: false,
            system: false,
        },
        {
            name: "subscription_status",
            type: "text",
            required: false,
            system: false,
        },
        {
            name: "plan",
            type: "text",
            required: false,
            system: false,
        },
        {
            name: "current_period_start",
            type: "date",
            required: false,
            system: false,
        },
        {
            name: "current_period_end",
            type: "date",
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
}, (app) => {
    const collection = app.findCollectionByNameOrId("tenants");

    const fieldsToRemove = [
        "stripe_customer_id",
        "subscription_id",
        "subscription_status",
        "plan",
        "current_period_start",
        "current_period_end",
    ];

    for (const name of fieldsToRemove) {
        const field = collection.fields.find(f => f.name === name);
        if (field) {
            collection.fields.removeById(field.id);
        }
    }

    return app.save(collection);
})
