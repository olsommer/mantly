/// <reference path="../pb_data/types.d.ts" />

/**
 * Store provider-reported LLM usage metadata per pipeline/eval run.
 */

function fieldExists(collection, name) {
    return !!collection.fields.find(f => f.name === name);
}

function addFieldIfMissing(app, collectionName, fieldDef) {
    const collection = app.findCollectionByNameOrId(collectionName);
    if (!fieldExists(collection, fieldDef.name)) {
        collection.fields.add(new Field(fieldDef));
        app.save(collection);
    }
    return collection;
}

function ensureCollection(app, def) {
    try {
        return app.findCollectionByNameOrId(def.name);
    } catch (_) {
        const col = new Collection(def);
        app.save(col);
        return col;
    }
}

migrate((app) => {
    try {
        addFieldIfMissing(app, "chats", {
            name: "token_usage",
            type: "json",
            required: false,
            system: false,
        });

        addFieldIfMissing(app, "eval_runs", {
            name: "token_usage",
            type: "json",
            required: false,
            system: false,
        });

        const tenants = app.findCollectionByNameOrId("tenants");
        const projects = app.findCollectionByNameOrId("projects");
        const chats = app.findCollectionByNameOrId("chats");
        const evalRuns = app.findCollectionByNameOrId("eval_runs");

        ensureCollection(app, {
            name: "llm_usage_events",
            type: "base",
            fields: [
                { name: "tenant", type: "relation", required: false, collectionId: tenants.id, maxSelect: 1, cascadeDelete: false },
                { name: "project", type: "relation", required: false, collectionId: projects.id, maxSelect: 1, cascadeDelete: false },
                { name: "chat", type: "relation", required: false, collectionId: chats.id, maxSelect: 1, cascadeDelete: false },
                { name: "eval_run", type: "relation", required: false, collectionId: evalRuns.id, maxSelect: 1, cascadeDelete: false },
                { name: "run_id", type: "text", required: false },
                { name: "stage", type: "text", required: false },
                { name: "provider", type: "text", required: false },
                { name: "model", type: "text", required: false },
                { name: "input_tokens", type: "number", required: false },
                { name: "output_tokens", type: "number", required: false },
                { name: "cached_input_tokens", type: "number", required: false },
                { name: "total_tokens", type: "number", required: false },
                { name: "metadata_available", type: "bool", required: false },
                { name: "raw_usage", type: "json", required: false },
                { name: "created", type: "autodate", onCreate: true, onUpdate: false, required: false },
                { name: "updated", type: "autodate", onCreate: true, onUpdate: true, required: false },
            ],
            indexes: [
                "CREATE INDEX idx_llm_usage_project_created ON llm_usage_events (project, created)",
                "CREATE INDEX idx_llm_usage_chat_created ON llm_usage_events (chat, created)",
                "CREATE INDEX idx_llm_usage_eval_run_created ON llm_usage_events (eval_run, created)",
            ],
            listRule: null,
            viewRule: null,
            createRule: null,
            updateRule: null,
            deleteRule: null,
        });
    } catch (_) {
        // Fresh sorted migration runs may execute before prerequisite collections exist.
        // Runtime schema bootstrap creates these fields/collections later.
    }
}, (app) => {
    try {
        const collection = app.findCollectionByNameOrId("llm_usage_events");
        app.delete(collection);
    } catch (_) {
        // Collection didn't exist; ignore.
    }

    for (const collectionName of ["eval_runs", "chats"]) {
        try {
            const collection = app.findCollectionByNameOrId(collectionName);
            const field = collection.fields.find(f => f.name === "token_usage");
            if (field) {
                collection.fields.removeById(field.id);
                app.save(collection);
            }
        } catch (_) {
            // Collection didn't exist; ignore.
        }
    }
});
