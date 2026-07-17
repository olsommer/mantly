/// <reference path="../pb_data/types.d.ts" />

/** One automatic outbound reply per logical inbound message and ticket. */

const automaticReplyIndex = "CREATE UNIQUE INDEX idx_support_outbound_issue_idempotency ON support_outbound_messages (issue, idempotency_key) WHERE idempotency_key <> ''";

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
        let outbound;
        try {
            outbound = app.findCollectionByNameOrId("support_outbound_messages");
        } catch (_) {
            // Fresh installs create support collections in the Python bootstrap.
            return;
        }
        addFieldIfMissing(outbound, { name: "idempotency_key", type: "text", required: false });
        if (!outbound.indexes.includes(automaticReplyIndex)) {
            outbound.indexes.push(automaticReplyIndex);
        }
        app.save(outbound);
    },
    (app) => {
        let outbound;
        try {
            outbound = app.findCollectionByNameOrId("support_outbound_messages");
        } catch (_) {
            return;
        }
        outbound.indexes = outbound.indexes.filter((index) => index !== automaticReplyIndex);
        removeFieldIfPresent(outbound, "idempotency_key");
        app.save(outbound);
    },
);
