/// <reference path="../pb_data/types.d.ts" />

/** Atomic, token-fenced ownership for generic channel-webhook events. */

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
        let events;
        try {
            events = app.findCollectionByNameOrId("support_channel_webhook_events");
        } catch (_) {
            return;
        }
        addFieldIfMissing(events, {
            name: "processing_claim_token",
            type: "text",
            required: false,
            hidden: true,
        });
        addFieldIfMissing(events, { name: "processing_claimed_at", type: "date", required: false });
        addFieldIfMissing(events, { name: "processing_claim_expires_at", type: "date", required: false });
        addFieldIfMissing(events, { name: "processing_attempt", type: "number", required: false });
        addFieldIfMissing(events, { name: "processing_retry_safe", type: "bool", required: false });
        addFieldIfMissing(events, { name: "retry_policy_version", type: "number", required: false });
        if (!events.indexes.includes(
            "CREATE INDEX idx_support_channel_webhook_claim ON support_channel_webhook_events (status, processing_claim_expires_at)",
        )) {
            events.indexes.push(
                "CREATE INDEX idx_support_channel_webhook_claim ON support_channel_webhook_events (status, processing_claim_expires_at)",
            );
        }
        app.save(events);
    },
    (app) => {
        let events;
        try {
            events = app.findCollectionByNameOrId("support_channel_webhook_events");
        } catch (_) {
            return;
        }
        for (const name of [
            "retry_policy_version",
            "processing_retry_safe",
            "processing_attempt",
            "processing_claim_expires_at",
            "processing_claimed_at",
            "processing_claim_token",
        ]) {
            removeFieldIfPresent(events, name);
        }
        events.indexes = events.indexes.filter(
            (index) => index !== "CREATE INDEX idx_support_channel_webhook_claim ON support_channel_webhook_events (status, processing_claim_expires_at)",
        );
        app.save(events);
    },
);
