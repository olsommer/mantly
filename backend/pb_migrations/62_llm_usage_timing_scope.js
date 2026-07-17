/// <reference path="../pb_data/types.d.ts" />

/**
 * Identify usage rows that share one recorded LLM stage wall-time measurement.
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
        let usageEvents;
        try {
            usageEvents = app.findCollectionByNameOrId("llm_usage_events");
        } catch (_) {
            // Fresh installs create this collection in the Python bootstrap.
            return;
        }
        for (const def of [
            { name: "stage_execution_id", type: "text", required: false },
            { name: "usage_record_id", type: "text", required: false },
            { name: "duration_scope", type: "text", required: false },
            { name: "usage_payload_index", type: "number", required: false },
            { name: "usage_payload_count", type: "number", required: false },
        ]) {
            addFieldIfMissing(usageEvents, def);
        }
        app.save(usageEvents);
    },
    (app) => {
        let usageEvents;
        try {
            usageEvents = app.findCollectionByNameOrId("llm_usage_events");
        } catch (_) {
            return;
        }
        for (const name of [
            "stage_execution_id",
            "usage_record_id",
            "duration_scope",
            "usage_payload_index",
            "usage_payload_count",
        ]) {
            removeFieldIfPresent(usageEvents, name);
        }
        app.save(usageEvents);
    },
);
