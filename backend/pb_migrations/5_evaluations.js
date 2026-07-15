/// <reference path="../pb_data/types.d.ts" />

/**
 * Mantly — evaluation collections for automated pipeline testing.
 *
 * Four collections:
 *   eval_sets    — groups of test cases
 *   eval_cases   — individual test emails with expected outcomes
 *   eval_runs    — a single execution of an eval set
 *   eval_results — per-case results with LLM judge scores
 */

function ensureCollection(app, def) {
    try {
        return app.findCollectionByNameOrId(def.name);
    } catch (_) {
        const col = new Collection(def);
        app.save(col);
        return col;
    }
}

migrate(
    // ── Apply ──────────────────────────────────────────────────────────────────
    (app) => {
        const tenants = app.findCollectionByNameOrId("tenants");

        // 1. Eval Sets — a named collection of test cases
        const eval_sets = ensureCollection(app, {
            name: "eval_sets",
            type: "base",
            fields: [
                { name: "tenant",      type: "relation", required: false, collectionId: tenants.id, maxSelect: 1, cascadeDelete: false },
                { name: "name",        type: "text",     required: true },
                { name: "description", type: "text",     required: false },
                { name: "created",     type: "autodate", onCreate: true,  onUpdate: false, required: false },
                { name: "updated",     type: "autodate", onCreate: true,  onUpdate: true,  required: false },
            ],
            indexes: [],
            listRule:   null,
            viewRule:   null,
            createRule: null,
            updateRule: null,
            deleteRule: null,
        });

        // 2. Eval Cases — individual test emails with expectations
        const eval_cases = ensureCollection(app, {
            name: "eval_cases",
            type: "base",
            fields: [
                { name: "eval_set",                type: "relation", required: true, collectionId: eval_sets.id, maxSelect: 1, cascadeDelete: false },
                { name: "name",                    type: "text",     required: true },
                // Email fields
                { name: "email_subject",           type: "text",     required: true },
                { name: "email_from",              type: "text",     required: true },
                { name: "email_body",              type: "editor",   required: true },
                { name: "email_attachments",       type: "json",     required: false },
                // Expected outcomes
                { name: "expected_customer_found", type: "bool",     required: false },
                { name: "expected_customer_data",  type: "json",     required: false },
                { name: "expected_intent_matched", type: "bool",     required: false },
                { name: "expected_intent_name",    type: "text",     required: false },
                { name: "expected_actions",        type: "json",     required: false },
                { name: "expected_requires_human", type: "bool",     required: false },
                { name: "expected_response",       type: "editor",   required: false },
                { name: "created",                 type: "autodate", onCreate: true,  onUpdate: false, required: false },
                { name: "updated",                 type: "autodate", onCreate: true,  onUpdate: true,  required: false },
            ],
            indexes: [],
            listRule:   null,
            viewRule:   null,
            createRule: null,
            updateRule: null,
            deleteRule: null,
        });

        // 3. Eval Runs — a single execution of an eval set
        const eval_runs = ensureCollection(app, {
            name: "eval_runs",
            type: "base",
            fields: [
                { name: "eval_set",     type: "relation", required: true,  collectionId: eval_sets.id, maxSelect: 1, cascadeDelete: false },
                { name: "tenant",       type: "relation", required: false, collectionId: tenants.id,   maxSelect: 1, cascadeDelete: false },
                { name: "status",       type: "text",     required: true },   // pending | running | completed | failed
                { name: "started_at",   type: "date",     required: false },
                { name: "completed_at", type: "date",     required: false },
                { name: "summary",      type: "json",     required: false },  // aggregate scores
                { name: "token_usage",  type: "json",     required: false },
                { name: "created",      type: "autodate", onCreate: true,  onUpdate: false, required: false },
                { name: "updated",      type: "autodate", onCreate: true,  onUpdate: true,  required: false },
            ],
            indexes: [],
            listRule:   null,
            viewRule:   null,
            createRule: null,
            updateRule: null,
            deleteRule: null,
        });

        // 4. Eval Results — per-case result with judge scores
        ensureCollection(app, {
            name: "eval_results",
            type: "base",
            fields: [
                { name: "eval_run",          type: "relation", required: true, collectionId: eval_runs.id,  maxSelect: 1, cascadeDelete: false },
                { name: "eval_case",         type: "relation", required: true, collectionId: eval_cases.id, maxSelect: 1, cascadeDelete: false },
                { name: "status",            type: "text",     required: true },   // pending | running | completed | failed
                { name: "pipeline_output",   type: "json",     required: false },  // full PipelineResult as dict
                // Judge scores (0–100)
                { name: "identity_score",    type: "number",   required: false },
                { name: "identity_reasoning",type: "editor",   required: false },
                { name: "intent_score",      type: "number",   required: false },
                { name: "intent_reasoning",  type: "editor",   required: false },
                { name: "actions_score",     type: "number",   required: false },
                { name: "actions_reasoning", type: "editor",   required: false },
                { name: "response_score",    type: "number",   required: false },
                { name: "response_reasoning",type: "editor",   required: false },
                { name: "overall_score",     type: "number",   required: false },
                { name: "error",             type: "text",     required: false },
                { name: "created",           type: "autodate", onCreate: true,  onUpdate: false, required: false },
                { name: "updated",           type: "autodate", onCreate: true,  onUpdate: true,  required: false },
            ],
            indexes: [],
            listRule:   null,
            viewRule:   null,
            createRule: null,
            updateRule: null,
            deleteRule: null,
        });
    },

    // ── Revert ─────────────────────────────────────────────────────────────────
    (app) => {
        // Delete in reverse dependency order
        const names = ["eval_results", "eval_runs", "eval_cases", "eval_sets"];
        for (const name of names) {
            try {
                const col = app.findCollectionByNameOrId(name);
                app.delete(col);
            } catch (_) {
                // Collection didn't exist — ignore
            }
        }
    },
);
