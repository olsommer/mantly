/// <reference path="../pb_data/types.d.ts" />

/**
 * Ticket merge redirect fields.
 */

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
        try {
            const issues = app.findCollectionByNameOrId("support_issues");
            addFieldIfMissing(issues, {
                name: "merged_into_issue",
                type: "relation",
                required: false,
                collectionId: issues.id,
                maxSelect: 1,
                cascadeDelete: false,
            });
            addFieldIfMissing(issues, { name: "merged_at", type: "date", required: false });
            addFieldIfMissing(issues, { name: "merged_by", type: "text", required: false });
            addFieldIfMissing(issues, { name: "merge_note", type: "editor", required: false });
            app.save(issues);
        } catch (_) {
            // Prerequisites missing. Runtime bootstrap creates the fields.
        }
    },
    (app) => {
        try {
            const issues = app.findCollectionByNameOrId("support_issues");
            for (const name of ["merge_note", "merged_by", "merged_at", "merged_into_issue"]) {
                removeFieldIfPresent(issues, name);
            }
            app.save(issues);
        } catch (_) {}
    },
);
