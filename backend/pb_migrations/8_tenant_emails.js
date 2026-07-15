/// <reference path="../pb_data/types.d.ts" />

/**
 * Add support_email and feedback_email fields to the tenants collection.
 *
 * These are displayed in the sidebar as mailto: links and are editable
 * by root users in the organisation settings page.
 */
migrate((app) => {
    const collection = app.findCollectionByNameOrId("tenants");

    const newFields = [
        {
            name: "support_email",
            type: "text",
            required: false,
            system: false,
        },
        {
            name: "feedback_email",
            type: "text",
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

    for (const name of ["support_email", "feedback_email"]) {
        const field = collection.fields.find(f => f.name === name);
        if (field) {
            collection.fields.removeById(field.id);
        }
    }

    return app.save(collection);
})
