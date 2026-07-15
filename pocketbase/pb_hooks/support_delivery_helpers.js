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

function issueTerminal(issue) {
    const status = issue.getString("status").toLowerCase();
    return ["done", "closed", "cancelled", "canceled"].indexOf(status) >= 0
        || !!issue.getString("merged_into_issue");
}

function conflict(message) {
    throw new ApiError(409, message);
}

module.exports = {
    OUTBOUND_COLLECTION: "support_outbound_messages",
    ISSUE_COLLECTION: "support_issues",
    text,
    jsonObject,
    issueTerminal,
    conflict,
    publicRecord: (record) => record.publicExport(),
};
