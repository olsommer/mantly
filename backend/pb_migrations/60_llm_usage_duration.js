/// <reference path="../pb_data/types.d.ts" />

/** Persist wall-clock duration for each recorded LLM stage. */

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
        let usageEvents;
        try {
            usageEvents = app.findCollectionByNameOrId("llm_usage_events");
        } catch (_) {
            // Fresh installs create this collection in the Python bootstrap.
            return;
        }
        addFieldIfMissing(usageEvents, {
            name: "duration_ms",
            type: "number",
            required: false,
        });
        app.save(usageEvents);
    },
    (app) => {
        let usageEvents;
        try {
            usageEvents = app.findCollectionByNameOrId("llm_usage_events");
        } catch (_) {
            return;
        }
        removeFieldIfPresent(usageEvents, "duration_ms");
        app.save(usageEvents);
    },
);
