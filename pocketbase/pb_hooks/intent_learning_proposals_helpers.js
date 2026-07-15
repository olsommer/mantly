"use strict";

const LEARNING_EVAL_POLICY_HASH = "eade510f204556964a0ac6f3938482c53e07dcf6598f6656ed647c99b2cdec8a";
const LEARNING_EVAL_SERVER_FLOOR = 80;
const MAX_ACTIVE_INTENT_LEARNINGS = 50;

function text(value) {
    return value == null ? "" : String(value).trim();
}

function jsonValue(record, field, fallback) {
    try {
        const parsed = JSON.parse(toString(record.get(field)) || JSON.stringify(fallback));
        return parsed == null ? fallback : parsed;
    } catch (_) {
        return fallback;
    }
}

function stages(record) {
    const raw = jsonValue(record, "affected_stages", []);
    if (!Array.isArray(raw)) {
        return [];
    }
    return raw.map((value) => text(value)).filter((value) => !!value);
}

function proposalHash(record) {
    const payload = {
        affected_stages: stages(record),
        base_learning_hash: record.getString("base_learning_hash"),
        before_learning: record.getString("before_learning"),
        intent_name: record.getString("intent_name"),
        operation: record.getString("operation"),
        project: record.getString("project"),
        proposed_learning: record.getString("proposed_learning"),
        runbook_id: record.getString("runbook_id"),
        runbook_updated: record.getString("runbook_updated"),
        source_feedback_id: record.getString("source_feedback_id"),
        target_learning_id: record.getString("target_learning_id"),
        tenant: record.getString("tenant"),
    };
    return $security.sha256(JSON.stringify(payload));
}

function activeSetHash(records) {
    const snapshot = records.map((record) => ({
        affected_stages: stages(record),
        id: record.id,
        learning: record.getString("learning"),
        source_feedback_id: record.getString("source_feedback_id"),
    }));
    snapshot.sort((left, right) => left.id.localeCompare(right.id));
    return $security.sha256(JSON.stringify(snapshot));
}

function evalCaseHash(records) {
    const snapshot = records.map((record) => ({
        id: record.id,
        updated: record.getDateTime("updated").string(),
    }));
    snapshot.sort((left, right) => left.id.localeCompare(right.id));
    return $security.sha256(JSON.stringify(snapshot));
}

function feedbackLearningsEnabled(runbook) {
    const response = jsonValue(runbook, "response", {});
    const configured = Object.prototype.hasOwnProperty.call(response, "use_feedback_learnings")
        ? response.use_feedback_learnings
        : true;
    if (typeof configured === "boolean") {
        return configured;
    }
    return ["false", "0", "no", "off"].indexOf(text(configured).toLowerCase()) < 0;
}

function conflict(message) {
    throw new ApiError(409, message);
}

module.exports = {
    LEARNING_EVAL_POLICY_HASH,
    LEARNING_EVAL_SERVER_FLOOR,
    MAX_ACTIVE_INTENT_LEARNINGS,
    text,
    jsonValue,
    stages,
    proposalHash,
    activeSetHash,
    evalCaseHash,
    feedbackLearningsEnabled,
    conflict,
};
