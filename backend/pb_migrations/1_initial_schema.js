/// <reference path="../pb_data/types.d.ts" />

/**
 * Mantly — initial PocketBase schema.
 *
 * Collections:
 *   tenants     — law firms / organisations (base collection)
 *   users       — auth collection; each user belongs to one tenant
 *   chats       — email analysis cache (replaces SQLite chats table)
 *
 * The apply function is IDEMPOTENT: it finds an existing collection and
 * returns it rather than failing if it was already partially created by a
 * previous failed migration run.
 */

/** Find an existing collection by name, or create and save it. Returns the collection. */
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

        // ── tenants ───────────────────────────────────────────────────────────
        const tenants = ensureCollection(app, {
            name: "tenants",
            type: "base",
            fields: [
                { name: "name", type: "text", required: true },
            ],
            listRule: null,
            viewRule: null,
            createRule: null,
            updateRule: null,
            deleteRule: null,
        });

        // ── users (auth collection) ────────────────────────────────────────────
        ensureCollection(app, {
            name: "users",
            type: "auth",
            fields: [
                {
                    name: "tenant",
                    type: "relation",
                    required: true,
                    collectionId: tenants.id,
                    maxSelect: 1,
                    cascadeDelete: false,
                },
            ],
            listRule: "@request.auth.id = id",
            viewRule: "@request.auth.id = id",
            createRule: "",
            updateRule: "@request.auth.id = id",
            deleteRule: null,
        });

        // ── chats ─────────────────────────────────────────────────────────────
        ensureCollection(app, {
            name: "chats",
            type: "base",
            fields: [
                { name: "email_id",        type: "text",  required: true },
                { name: "creator",         type: "text",  required: true },
                { name: "messages",        type: "json",  required: false },
                { name: "status",          type: "text",  required: false },
                { name: "members",         type: "json",  required: false },
                { name: "subject",         type: "text",  required: false },
                { name: "from_address",    type: "text",  required: false },
                { name: "activated_intent", type: "text",  required: false },
                { name: "requires_human",  type: "bool",  required: false },
                { name: "identity_result", type: "json",  required: false },
                { name: "intent_result",   type: "json",  required: false },
                { name: "phishing_result", type: "json",  required: false },
                { name: "prompt_injection_result", type: "json", required: false },
                { name: "token_usage",     type: "json",  required: false },
                {
                    name: "tenant",
                    type: "relation",
                    required: false,
                    collectionId: tenants.id,
                    maxSelect: 1,
                    cascadeDelete: false,
                },
                { name: "created", type: "autodate", onCreate: true,  onUpdate: false, required: false },
                { name: "updated", type: "autodate", onCreate: true,  onUpdate: true,  required: false },
            ],
            listRule:   "tenant = @request.auth.tenant",
            viewRule:   "tenant = @request.auth.tenant",
            createRule: "tenant = @request.auth.tenant",
            updateRule: "tenant = @request.auth.tenant",
            deleteRule: null,
        });
    },

    // ── Revert ─────────────────────────────────────────────────────────────────
    (app) => {
        for (const name of ["chats", "users", "tenants"]) {
            try {
                const col = app.findCollectionByNameOrId(name);
                app.delete(col);
            } catch (_) {
                // Collection didn't exist — ignore
            }
        }
    },
);
