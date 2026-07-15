migrate((app) => {
    const users = app.findCollectionByNameOrId("users");

    // Add must_change_password field — true when admin creates a user
    if (!users.fields.getByName("must_change_password")) {
        users.fields.add(new BoolField({
            name: "must_change_password",
            required: false,
        }));
    }

    // Restrict user creation to admin/superuser only (no public self-signup)
    users.createRule = null;

    app.save(users);
}, (app) => {
    const users = app.findCollectionByNameOrId("users");
    const field = users.fields.getByName("must_change_password");
    if (field) {
        users.fields.remove(field);
    }
    users.createRule = "";
    app.save(users);
});
