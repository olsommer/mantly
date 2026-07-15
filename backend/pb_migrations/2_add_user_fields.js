/// <reference path="../pb_data/types.d.ts" />

/**
 * Adds the `tenant` relation field to the `users` auth collection if missing.
 *
 * This is necessary because PocketBase ships with a built-in `users` auth
 * collection. Migration 1_initial_schema.js used ensureCollection() which
 * returns the existing collection as-is when it already exists — meaning the
 * custom fields were never applied on a fresh PocketBase install.
 */
migrate(
    (app) => {
        const users = app.findCollectionByNameOrId("users");
        const tenants = app.findCollectionByNameOrId("tenants");

        let changed = false;

        if (!users.fields.getByName("tenant")) {
            users.fields.add(new RelationField({
                name: "tenant",
                required: false,   // false so existing users without a tenant aren't broken
                collectionId: tenants.id,
                maxSelect: 1,
                cascadeDelete: false,
            }));
            changed = true;
        }

        if (changed) {
            app.save(users);
        }
    },

    (app) => {
        try {
            const users = app.findCollectionByNameOrId("users");
            for (const name of ["tenant"]) {
                const f = users.fields.getByName(name);
                if (f) users.fields.remove(f);
            }
            app.save(users);
        } catch (_) {}
    }
);
