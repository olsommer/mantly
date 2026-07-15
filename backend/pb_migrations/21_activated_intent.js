/// <reference path="../pb_data/types.d.ts" />

/**
 * Rename chats.activated_skill to chats.activated_intent.
 */

function addTextFieldIfMissing(collection, name) {
    if (!collection.fields.find(f => f.name === name)) {
        collection.fields.add(new Field({
            name,
            type: "text",
            required: false,
            system: false,
        }));
    }
}

function removeFieldIfPresent(collection, name) {
    const field = collection.fields.find(f => f.name === name);
    if (field) {
        collection.fields.removeById(field.id);
    }
}

migrate((app) => {
    try {
        const collection = app.findCollectionByNameOrId("chats");
        const hasOld = !!collection.fields.find(f => f.name === "activated_skill");

        addTextFieldIfMissing(collection, "activated_intent");
        app.save(collection);

        if (hasOld) {
            app.db()
                .newQuery(
                    "UPDATE chats SET activated_intent = activated_skill " +
                    "WHERE (activated_intent IS NULL OR activated_intent = '') " +
                    "AND activated_skill IS NOT NULL AND activated_skill != ''"
                )
                .execute();

            app.db()
                .newQuery(
                    "UPDATE chats SET messages = replace(messages, '\"activatedSkill\"', '\"activatedIntent\"') " +
                    "WHERE messages LIKE '%\"activatedSkill\"%'"
                )
                .execute();

            app.db()
                .newQuery(
                    "UPDATE chats SET messages = replace(messages, '\"activated_skill\"', '\"activated_intent\"') " +
                    "WHERE messages LIKE '%\"activated_skill\"%'"
                )
                .execute();

            removeFieldIfPresent(collection, "activated_skill");
            app.save(collection);
        }
    } catch (_) {
        // Fresh sorted migration runs may execute before chats exists.
        // Runtime schema bootstrap / initial schema creates activated_intent later.
    }
}, (app) => {
    try {
        const collection = app.findCollectionByNameOrId("chats");
        const hasNew = !!collection.fields.find(f => f.name === "activated_intent");

        addTextFieldIfMissing(collection, "activated_skill");
        app.save(collection);

        if (hasNew) {
            app.db()
                .newQuery(
                    "UPDATE chats SET activated_skill = activated_intent " +
                    "WHERE (activated_skill IS NULL OR activated_skill = '') " +
                    "AND activated_intent IS NOT NULL AND activated_intent != ''"
                )
                .execute();

            app.db()
                .newQuery(
                    "UPDATE chats SET messages = replace(messages, '\"activatedIntent\"', '\"activatedSkill\"') " +
                    "WHERE messages LIKE '%\"activatedIntent\"%'"
                )
                .execute();

            app.db()
                .newQuery(
                    "UPDATE chats SET messages = replace(messages, '\"activated_intent\"', '\"activated_skill\"') " +
                    "WHERE messages LIKE '%\"activated_intent\"%'"
                )
                .execute();

            removeFieldIfPresent(collection, "activated_intent");
            app.save(collection);
        }
    } catch (_) {}
});
