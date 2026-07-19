"use strict";

function text(value) {
    return value == null ? "" : String(value).trim();
}

function jsonObject(record, field) {
    try {
        const parsed = JSON.parse(toString(record.get(field)) || "{}");
        return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch (_) {
        return {};
    }
}

function conflict(message) {
    throw new ApiError(409, message);
}

function inScope(record, projectId, tenantId) {
    return record.getString("project") === projectId
        && (!tenantId || record.getString("tenant") === tenantId);
}

module.exports = {
    CHANNEL_EVENT_COLLECTION: "support_channel_webhook_events",
    RETRY_POLICY_VERSION: 1,
    text,
    jsonObject,
    conflict,
    inScope,
    publicRecord: (record) => record.publicExport(),
};
