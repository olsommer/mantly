/// <reference path="../pb_data/types.d.ts" />

/**
 * Support collaboration, SLA, channel, and knowledge collections.
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

            ensureCollection(app, {
                name: "support_internal_notes",
                type: "base",
                fields: [
                    { name: "tenant",       type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",      type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "issue",        type: "relation", required: true,  collectionId: issues.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "author_email", type: "text",     required: false },
                    { name: "body",         type: "editor",   required: true },
                    { name: "visibility",   type: "text",     required: false },
                    { name: "metadata",     type: "json",     required: false },
                    { name: "created",      type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",      type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: ["CREATE INDEX idx_support_notes_issue_created ON support_internal_notes (issue, created)"],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });

            ensureCollection(app, {
                name: "support_issue_assignments",
                type: "base",
                fields: [
                    { name: "tenant",         type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",        type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "issue",          type: "relation", required: true,  collectionId: issues.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "assignee_email", type: "text",     required: false },
                    { name: "assigned_by",    type: "text",     required: false },
                    { name: "status",         type: "text",     required: false },
                    { name: "created",        type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",        type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_support_assignments_issue_created ON support_issue_assignments (issue, created)",
                    "CREATE INDEX idx_support_assignments_assignee_created ON support_issue_assignments (assignee_email, created)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });

            ensureCollection(app, {
                name: "support_sla_events",
                type: "base",
                fields: [
                    { name: "tenant",      type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",     type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "issue",       type: "relation", required: true,  collectionId: issues.id,   maxSelect: 1, cascadeDelete: true },
                    { name: "event_type",  type: "text",     required: true },
                    { name: "status",      type: "text",     required: true },
                    { name: "target_at",   type: "date",     required: false },
                    { name: "occurred_at", type: "date",     required: false },
                    { name: "metadata",    type: "json",     required: false },
                    { name: "created",     type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",     type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_sla_issue_type ON support_sla_events (issue, event_type)",
                    "CREATE INDEX idx_support_sla_project_status_target ON support_sla_events (project, status, target_at)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });

            ensureCollection(app, {
                name: "support_channels",
                type: "base",
                fields: [
                    { name: "tenant",       type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",      type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "channel_key",  type: "text",     required: true },
                    { name: "type",         type: "text",     required: true },
                    { name: "name",         type: "text",     required: true },
                    { name: "status",       type: "text",     required: false },
                    { name: "config",       type: "json",     required: false },
                    { name: "last_sync_at", type: "date",     required: false },
                    { name: "created",      type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",      type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_support_channels_project_key ON support_channels (project, channel_key)",
                    "CREATE INDEX idx_support_channels_project_type ON support_channels (project, type)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });

            ensureCollection(app, {
                name: "knowledge_articles",
                type: "base",
                fields: [
                    { name: "tenant",       type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",      type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "source_issue", type: "relation", required: false, collectionId: issues.id,   maxSelect: 1, cascadeDelete: false },
                    { name: "title",        type: "text",     required: true },
                    { name: "body",         type: "editor",   required: true },
                    { name: "status",       type: "text",     required: true },
                    { name: "tags",         type: "json",     required: false },
                    { name: "metadata",     type: "json",     required: false },
                    { name: "created",      type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated",      type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE INDEX idx_knowledge_articles_project_updated ON knowledge_articles (project, updated)",
                    "CREATE INDEX idx_knowledge_articles_project_status ON knowledge_articles (project, status)",
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
        for (const name of [
            "knowledge_articles",
            "support_channels",
            "support_sla_events",
            "support_issue_assignments",
            "support_internal_notes",
        ]) {
            try {
                const col = app.findCollectionByNameOrId(name);
                app.delete(col);
            } catch (_) {}
        }
    },
);
