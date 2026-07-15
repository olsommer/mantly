/// <reference path="../pb_data/types.d.ts" />

/**
 * Mantly — licenses collection for on-prem phone-home validation.
 *
 * Each license record represents a paid on-prem deployment.  The on-prem
 * instance calls the SaaS server's /api/license/validate endpoint
 * periodically, which looks up the license here.
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
        ensureCollection(app, {
            name: "licenses",
            type: "base",
            fields: [
                // Unique license key (e.g. UUID4) — sent by on-prem instances
                { name: "key",           type: "text", required: true },
                // Human-readable label for this license
                { name: "tenant_name",   type: "text", required: true },
                // Maximum number of users the license allows
                { name: "max_users",     type: "number", required: false },
                // Expiry date (ISO 8601) — empty means perpetual
                { name: "expires_at",    type: "date", required: false },
                // Whether the license is currently active (can be revoked)
                { name: "is_active",     type: "bool", required: false },
                // Instance fingerprint — bound on first validation call
                { name: "instance_id",   type: "text", required: false },
                // Stripe subscription ID — set when auto-provisioned via webhook
                { name: "subscription_id", type: "text", required: false },
                { name: "created", type: "autodate", onCreate: true,  onUpdate: false, required: false },
                { name: "updated", type: "autodate", onCreate: true,  onUpdate: true,  required: false },
            ],
            indexes: [
                "CREATE UNIQUE INDEX idx_licenses_key ON licenses (key)",
            ],
            // Licenses are managed via the SaaS admin — no user-facing API rules
            listRule:   null,
            viewRule:   null,
            createRule: null,
            updateRule: null,
            deleteRule: null,
        });
    },

    // ── Revert ─────────────────────────────────────────────────────────────────
    (app) => {
        try {
            const col = app.findCollectionByNameOrId("licenses");
            app.delete(col);
        } catch (_) {
            // Collection didn't exist — ignore
        }
    },
);
