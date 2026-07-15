/// <reference path="../pb_data/types.d.ts" />

/**
 * Rewrite all existing PocketBase record IDs from the default 15-char format
 * to 10-char lowercase alphanumeric nanoids (a-z0-9).
 *
 * PB stores relation fields as plain TEXT columns — there are no real SQL
 * FOREIGN KEY constraints — so we can safely UPDATE ids and patch FK references
 * in a single transaction.
 *
 * After this migration users must re-login (existing JWTs reference old user IDs).
 */
migrate((app) => {
    const ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789";
    const ID_LEN = 6;

    function nanoid() {
        let id = "";
        for (let i = 0; i < ID_LEN; i++) {
            id += ALPHABET[Math.floor(Math.random() * ALPHABET.length)];
        }
        return id;
    }

    // ── FK reference map ────────────────────────────────────────────────
    // When a collection's ID changes, which (table, column) pairs reference it?
    const FK_MAP = {
        tenants: [
            ["users", "tenant"],
            ["projects", "tenant"],
            ["chats", "tenant"],
            ["eval_sets", "tenant"],
            ["eval_runs", "tenant"],
        ],
        users: [
            ["project_members", "user"],
        ],
        projects: [
            ["project_members", "project"],
            ["chats", "project"],
            ["eval_sets", "project"],
        ],
        eval_sets: [
            ["eval_cases", "eval_set"],
            ["eval_runs", "eval_set"],
        ],
        eval_runs: [
            ["eval_results", "eval_run"],
        ],
        eval_cases: [
            ["eval_results", "eval_case"],
        ],
    };

    // Collections with no FK references pointing to them — only need ID rewrite
    const LEAF_COLLECTIONS = [
        "licenses",
        "project_members",
        "chats",
        "eval_results",
    ];

    // Process collections that have FK dependents first (order matters:
    // parent tables before children so FK updates target the correct old IDs)
    const ORDERED_PARENTS = [
        "tenants",
        "users",
        "projects",
        "eval_sets",
        "eval_cases",
        "eval_runs",
    ];

    // Rewrite a collection's IDs and update all FK references
    for (const collName of ORDERED_PARENTS) {
        const rows = arrayOf(new DynamicModel({ "id": "" }));
        app.db().newQuery("SELECT id FROM " + collName).all(rows);

        for (const row of rows) {
            const oldId = row.id;
            // Skip if already 10-char nanoid format
            if (oldId.length === ID_LEN) continue;

            const newId = nanoid();

            // Update the record's own ID
            app.db()
                .newQuery("UPDATE " + collName + " SET id = {:new} WHERE id = {:old}")
                .bind({ new: newId, old: oldId })
                .execute();

            // Update all FK references
            const refs = FK_MAP[collName] || [];
            for (const [refTable, refCol] of refs) {
                app.db()
                    .newQuery(
                        "UPDATE " + refTable +
                        " SET " + refCol + " = {:new}" +
                        " WHERE " + refCol + " = {:old}"
                    )
                    .bind({ new: newId, old: oldId })
                    .execute();
            }
        }
    }

    // Rewrite leaf collections (no FK dependents — just the ID itself)
    for (const collName of LEAF_COLLECTIONS) {
        const rows = arrayOf(new DynamicModel({ "id": "" }));
        app.db().newQuery("SELECT id FROM " + collName).all(rows);

        for (const row of rows) {
            const oldId = row.id;
            if (oldId.length === ID_LEN) continue;

            const newId = nanoid();
            app.db()
                .newQuery("UPDATE " + collName + " SET id = {:new} WHERE id = {:old}")
                .bind({ new: newId, old: oldId })
                .execute();
        }
    }
}, (app) => {
    // Down migration: no-op.  The old IDs cannot be restored; a DB backup
    // should be taken before running this migration.
})
