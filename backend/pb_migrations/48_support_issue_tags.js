/// <reference path="../pb_data/types.d.ts" />

/**
 * Issue labels for cross-cutting inbox triage.
 */

function ensureField(collection, field) {
    if (!collection.fields.find(f => f.name === field.name)) {
        collection.fields.add(new Field(field));
    }
}

migrate(
    (app) => {
        try {
            const issues = app.findCollectionByNameOrId("support_issues");
            ensureField(issues, { name: "tags", type: "json", required: false });
            app.save(issues);
        } catch (_) {
            // Runtime bootstrap creates the field when prerequisites are absent.
        }
    },
    (app) => {
        try {
            const issues = app.findCollectionByNameOrId("support_issues");
            const field = issues.fields.find(f => f.name === "tags");
            if (field) {
                issues.fields.removeById(field.id);
                app.save(issues);
            }
        } catch (_) {}
    },
);
