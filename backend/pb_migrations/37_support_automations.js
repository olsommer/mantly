/// <reference path="../pb_data/types.d.ts" />

/**
 * Support workflow automation rules and execution history.
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
    (app) => {
        try {
            const tenants = app.findCollectionByNameOrId("tenants");
            const projects = app.findCollectionByNameOrId("projects");
            const issues = app.findCollectionByNameOrId("support_issues");

            const rules = ensureCollection(app, {
                name: "support_automation_rules",
                type: "base",
                fields: [
                    { name: "tenant",      type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",     type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "name",        type: "text",     required: true },
                    { name: "active",      type: "bool",     required: false },
                    { name: "trigger",     type: "text",     required: true },
                    { name: "conditions",  type: "json",     required: false },
                    { name: "actions",     type: "json",     required: false },
                    { name: "last_run_at", type: "date",     required: false },
                    { name: "created",     type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",     type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_support_automation_rules_project_trigger ON support_automation_rules (project, trigger, active)",
                    "CREATE INDEX idx_support_automation_rules_project_name ON support_automation_rules (project, name)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });

            ensureCollection(app, {
                name: "support_automation_runs",
                type: "base",
                fields: [
                    { name: "tenant",          type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",         type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "rule",            type: "relation", required: true,  collectionId: rules.id,    maxSelect: 1, cascadeDelete: true },
                    { name: "issue",           type: "relation", required: true,  collectionId: issues.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "trigger",         type: "text",     required: false },
                    { name: "status",          type: "text",     required: false },
                    { name: "actions_applied", type: "number",   required: false },
                    { name: "error",           type: "editor",   required: false },
                    { name: "context",         type: "json",     required: false },
                    { name: "result",          type: "json",     required: false },
                    { name: "started_at",      type: "date",     required: false },
                    { name: "completed_at",    type: "date",     required: false },
                    { name: "created",         type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",         type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_support_automation_runs_rule_started ON support_automation_runs (rule, started_at)",
                    "CREATE INDEX idx_support_automation_runs_project_status ON support_automation_runs (project, status, started_at)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });
        } catch (_) {
            // Prerequisites missing. Runtime bootstrap creates collections.
        }
    },
    (app) => {
        try {
            app.delete(app.findCollectionByNameOrId("support_automation_runs"));
        } catch (_) {}
        try {
            app.delete(app.findCollectionByNameOrId("support_automation_rules"));
        } catch (_) {}
    },
);
