/// <reference path="../pb_data/types.d.ts" />

/**
 * External CRM object read model and sync observations.
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
            const accounts = app.findCollectionByNameOrId("support_accounts");
            const contacts = app.findCollectionByNameOrId("support_contacts");
            const issues = app.findCollectionByNameOrId("support_issues");

            ensureCollection(app, {
                name: "support_external_objects",
                type: "base",
                fields: [
                    { name: "tenant",        type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",       type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "account",       type: "relation", required: false, collectionId: accounts.id, maxSelect: 1, cascadeDelete: false },
                    { name: "contact",       type: "relation", required: false, collectionId: contacts.id, maxSelect: 1, cascadeDelete: false },
                    { name: "provider",      type: "text",     required: true },
                    { name: "object_type",   type: "text",     required: true },
                    { name: "external_id",   type: "text",     required: true },
                    { name: "external_url",  type: "text",     required: false },
                    { name: "display_name",  type: "text",     required: false },
                    { name: "raw",           type: "json",     required: false },
                    { name: "last_seen_at",  type: "date",     required: false },
                    { name: "created",       type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",       type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_external_objects_project_key ON support_external_objects (project, provider, object_type, external_id)",
                    "CREATE INDEX idx_support_external_objects_account_seen ON support_external_objects (account, last_seen_at)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });

            ensureCollection(app, {
                name: "support_external_sync_runs",
                type: "base",
                fields: [
                    { name: "tenant",       type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",      type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "account",      type: "relation", required: false, collectionId: accounts.id, maxSelect: 1, cascadeDelete: false },
                    { name: "source_issue", type: "relation", required: false, collectionId: issues.id, maxSelect: 1, cascadeDelete: false },
                    { name: "provider",     type: "text",     required: true },
                    { name: "status",       type: "text",     required: true },
                    { name: "objects_seen", type: "number",   required: false },
                    { name: "error",        type: "editor",   required: false },
                    { name: "result",       type: "json",     required: false },
                    { name: "started_at",   type: "date",     required: false },
                    { name: "completed_at", type: "date",     required: false },
                    { name: "created",      type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",      type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_support_external_sync_runs_account_started ON support_external_sync_runs (account, started_at)",
                    "CREATE INDEX idx_support_external_sync_runs_project_status ON support_external_sync_runs (project, status, started_at)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });
        } catch (_) {
            // Prerequisites missing. Runtime bootstrap creates the collections.
        }
    },
    (app) => {
        for (const name of ["support_external_sync_runs", "support_external_objects"]) {
            try {
                app.delete(app.findCollectionByNameOrId(name));
            } catch (_) {}
        }
    },
);
