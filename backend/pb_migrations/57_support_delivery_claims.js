/// <reference path="../pb_data/types.d.ts" />

/**
 * Atomic outbound-delivery claim state.
 *
 * Provider calls cannot participate in the PocketBase transaction. A short,
 * token-fenced claim prevents multiple workers from sending the same reply.
 */

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
        addFieldIfMissing(outbound, { name: "delivery_claim_token", type: "text", required: false, hidden: true });
        addFieldIfMissing(outbound, { name: "delivery_attempt_key", type: "text", required: false });
        addFieldIfMissing(outbound, { name: "delivery_claimed_at", type: "date", required: false });
        addFieldIfMissing(outbound, { name: "delivery_claim_expires_at", type: "date", required: false });
        if (!outbound.indexes.includes("CREATE INDEX idx_support_outbound_delivery_claim ON support_outbound_messages (status, delivery_claim_expires_at)")) {
            outbound.indexes.push("CREATE INDEX idx_support_outbound_delivery_claim ON support_outbound_messages (status, delivery_claim_expires_at)");
        }
        // Collection exists: field, index, or save errors must fail deployment.
        app.save(outbound);
    },
    (app) => {
        let outbound;
        try {
            outbound = app.findCollectionByNameOrId("support_outbound_messages");
        } catch (_) {
            return;
        }
        for (const name of [
            "delivery_claim_expires_at",
            "delivery_claimed_at",
            "delivery_attempt_key",
            "delivery_claim_token",
        ]) {
            removeFieldIfPresent(outbound, name);
        }
        outbound.indexes = outbound.indexes.filter(
            (index) => index !== "CREATE INDEX idx_support_outbound_delivery_claim ON support_outbound_messages (status, delivery_claim_expires_at)",
        );
        app.save(outbound);
    },
);
