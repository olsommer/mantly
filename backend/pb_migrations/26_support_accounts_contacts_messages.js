/// <reference path="../pb_data/types.d.ts" />

/**
 * Account, contact, and normalized message records for support workspace.
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
            const tenants = app.findCollectionByNameOrId("tenants");
            const projects = app.findCollectionByNameOrId("projects");
            const issues = app.findCollectionByNameOrId("support_issues");

            const accounts = ensureCollection(app, {
                name: "support_accounts",
                type: "base",
                fields: [
                    { name: "tenant",          type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",         type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "account_key",     type: "text",     required: true },
                    { name: "name",            type: "text",     required: false },
                    { name: "domain",          type: "text",     required: false },
                    { name: "external_id",     type: "text",     required: false },
                    { name: "health_status",   type: "text",     required: false },
                    { name: "metadata",        type: "json",     required: false },
                    { name: "issue_count",     type: "number",   required: false },
                    { name: "latest_issue_at", type: "date",     required: false },
                    { name: "created",         type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",         type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_accounts_project_key ON support_accounts (project, account_key)",
                    "CREATE INDEX idx_support_accounts_project_updated ON support_accounts (project, updated)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });

            const contacts = ensureCollection(app, {
                name: "support_contacts",
                type: "base",
                fields: [
                    { name: "tenant",          type: "relation", required: false, collectionId: tenants.id,   maxSelect: 1, cascadeDelete: false },
                    { name: "project",         type: "relation", required: true,  collectionId: projects.id,  maxSelect: 1, cascadeDelete: true },
                    { name: "account",         type: "relation", required: false, collectionId: accounts.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "contact_key",     type: "text",     required: true },
                    { name: "email",           type: "text",     required: false },
                    { name: "name",            type: "text",     required: false },
                    { name: "external_id",     type: "text",     required: false },
                    { name: "metadata",        type: "json",     required: false },
                    { name: "issue_count",     type: "number",   required: false },
                    { name: "latest_issue_at", type: "date",     required: false },
                    { name: "created",         type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",         type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_contacts_project_key ON support_contacts (project, contact_key)",
                    "CREATE INDEX idx_support_contacts_account_updated ON support_contacts (account, updated)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });

            addFieldIfMissing(issues, { name: "account", type: "relation", required: false, collectionId: accounts.id, maxSelect: 1, cascadeDelete: false });
            addFieldIfMissing(issues, { name: "contact", type: "relation", required: false, collectionId: contacts.id, maxSelect: 1, cascadeDelete: false });
            app.save(issues);

            ensureCollection(app, {
                name: "support_messages",
                type: "base",
                fields: [
                    { name: "tenant",            type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",           type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "issue",             type: "relation", required: true,  collectionId: issues.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "source_message_id", type: "text",     required: true },
                    { name: "direction",         type: "text",     required: true },
                    { name: "sender",            type: "text",     required: false },
                    { name: "body",              type: "editor",   required: false },
                    { name: "message_kind",      type: "text",     required: false },
                    { name: "attachments",       type: "json",     required: false },
                    { name: "metadata",          type: "json",     required: false },
                    { name: "occurred_at",       type: "date",     required: false },
                    { name: "created",           type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",           type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_messages_issue_source ON support_messages (issue, source_message_id)",
                    "CREATE INDEX idx_support_messages_issue_occurred ON support_messages (issue, occurred_at)",
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
        for (const name of ["support_messages", "support_contacts", "support_accounts"]) {
            try {
                const col = app.findCollectionByNameOrId(name);
                app.delete(col);
            } catch (_) {}
        }
        try {
            const issues = app.findCollectionByNameOrId("support_issues");
            removeFieldIfPresent(issues, "account");
            removeFieldIfPresent(issues, "contact");
            app.save(issues);
        } catch (_) {}
    },
);
