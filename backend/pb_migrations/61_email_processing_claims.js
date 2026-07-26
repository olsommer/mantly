/// <reference path="../pb_data/types.d.ts" />

/**
 * Durable cross-worker ownership for connected-channel email processing.
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

            ensureCollection(app, {
                name: "email_processing_claims",
                type: "base",
                fields: [
                    { name: "tenant",      type: "relation", required: false, collectionId: tenants.id,  maxSelect: 1, cascadeDelete: false },
                    { name: "project",     type: "relation", required: true,  collectionId: projects.id, maxSelect: 1, cascadeDelete: true },
                    { name: "claim_key",   type: "text",     required: true },
                    { name: "email_id",    type: "text",     required: true },
                    { name: "attempt",     type: "number",   required: true },
                    { name: "owner_token", type: "text",     required: true, hidden: true },
                    { name: "status",      type: "text",     required: true },
                    { name: "lease_until", type: "date",     required: true },
                    { name: "error",       type: "text",     required: false },
                    { name: "created", type: "autodate", onCreate: true, onUpdate: false, required: false },
                    { name: "updated", type: "autodate", onCreate: true, onUpdate: true,  required: false },
                ],
                indexes: [
                    "CREATE UNIQUE INDEX idx_email_processing_claim_attempt ON email_processing_claims (project, claim_key, attempt)",
                    "CREATE INDEX idx_email_processing_claim_status ON email_processing_claims (project, status, lease_until)",
                ],
                listRule: null,
                viewRule: null,
                createRule: null,
                updateRule: null,
                deleteRule: null,
            });
        } catch (_) {
            // Prerequisites missing. Runtime bootstrap creates the collection.
        }
    },
    (app) => {
        try {
            const col = app.findCollectionByNameOrId("email_processing_claims");
            app.delete(col);
        } catch (_) {}
    },
);
