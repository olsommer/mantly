/// <reference path="../pb_data/types.d.ts" />

/**
 * JSON metadata for support issues.
 *
 * Used for project-defined custom ticket fields and future ticket attributes.
 */

function ensureField(collection, field) {
    if (!collection.fields.find(f => f.name === field.name)) {
        collection.fields.add(new Field(field));
    }
}

migrate(
    (app) => {
        try {
            const col = app.findCollectionByNameOrId("support_issues");
            ensureField(col, { name: "metadata", type: "json", required: false });
            app.save(col);
        } catch (_) {
            // Runtime bootstrap creates or repairs the field when prerequisites exist.
        }
    },
    (app) => {
        try {
            const col = app.findCollectionByNameOrId("support_issues");
            const field = col.fields.find(f => f.name === "metadata");
            if (field) {
                col.fields.removeById(field.id);
                app.save(col);
            }
        } catch (_) {}
    },
);
