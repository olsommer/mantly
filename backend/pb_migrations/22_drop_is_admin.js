/// <reference path="../pb_data/types.d.ts" />

/**
 * Drop the old users.is_admin field. is_root is now the only root-user flag.
 */
migrate(
    (app) => {
        try {
            const users = app.findCollectionByNameOrId("users");
            const field = users.fields.getByName("is_admin");
            if (!field) return;
            users.fields.remove(field);
            app.save(users);
        } catch (_) {
            // Fresh sorted migration runs may execute before users exists.
        }
    },
    (app) => {
        // No down migration. is_root remains the canonical root-user flag.
    },
);
