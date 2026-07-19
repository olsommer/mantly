/// <reference path="../../backend/pb_data/types.d.ts" />

/** Transactional generic channel-webhook claims and token-fenced completion. */

const CHANNEL_EVENT_COLLECTION = "support_channel_webhook_events";
const RETRY_POLICY_VERSION = 1;

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

routerAdd(
    "POST",
    "/api/mantly/support-channel-webhooks/{id}/claim",
    (e) => {
        const id = e.request.pathValue("id");
        const body = e.requestInfo().body || {};
        const projectId = text(body.project_id);
        const tenantId = text(body.tenant_id);
        const retryPolicyVersion = Number(body.retry_policy_version) || 0;
        const allowFailed = body.allow_failed === true;
        const maxAttempts = Math.max(1, Math.min(5, Number(body.max_attempts) || 3));
        const leaseSeconds = Math.max(60, Math.min(3600, Number(body.lease_seconds) || 900));
        const workerId = text(body.worker_id).slice(0, 200);
        if (!id || !projectId || retryPolicyVersion !== RETRY_POLICY_VERSION) {
            throw new BadRequestError("invalid_channel_webhook_claim");
        }

        let response = null;
        e.app.runInTransaction((txApp) => {
            const before = txApp.findRecordById(CHANNEL_EVENT_COLLECTION, id);
            if (!inScope(before, projectId, tenantId)) {
                conflict("channel_webhook_claim_scope_changed");
            }
            const priorStatus = before.getString("status").toLowerCase();
            if (["processed", "skipped", "unmatched"].indexOf(priorStatus) >= 0) {
                response = {
                    claimed: false,
                    state: priorStatus,
                    event: before.publicExport(),
                };
                return;
            }

            const token = $security.randomString(32);
            const claimedAt = new DateTime().string();
            const expiresAt = new DateTime(
                new Date(Date.now() + leaseSeconds * 1000).toISOString(),
            ).string();
            const claim = txApp.db().newQuery(
                "UPDATE support_channel_webhook_events "
                + "SET status = 'received', processing_claim_token = {:token}, "
                + "processing_claimed_at = {:claimedAt}, processing_claim_expires_at = {:expiresAt}, "
                + "processing_attempt = COALESCE(processing_attempt, 0) + 1, "
                + "processing_retry_safe = 0, retry_policy_version = {:retryPolicyVersion} "
                + "WHERE id = {:id} AND project = {:projectId} "
                + "AND ({:tenantId} = '' OR tenant = {:tenantId}) AND ("
                + "(status = 'received' AND (processing_claim_token = '' OR processing_claim_token IS NULL "
                + "OR processing_claim_expires_at = '' OR processing_claim_expires_at IS NULL "
                + "OR processing_claim_expires_at <= {:claimedAt})) "
                + "OR ({:allowFailed} = 1 AND status = 'failed' "
                + "AND processing_retry_safe = 1 AND retry_policy_version = {:retryPolicyVersion} "
                + "AND COALESCE(processing_attempt, 0) < {:maxAttempts})"
                + ")",
            ).bind({
                id,
                projectId,
                tenantId,
                token,
                claimedAt,
                expiresAt,
                allowFailed: allowFailed ? 1 : 0,
                maxAttempts,
                retryPolicyVersion,
            }).execute();

            if (claim.rowsAffected() !== 1) {
                const current = txApp.findRecordById(CHANNEL_EVENT_COLLECTION, id);
                response = {
                    claimed: false,
                    state: current.getString("status") || "received",
                    event: current.publicExport(),
                };
                return;
            }

            const event = txApp.findRecordById(CHANNEL_EVENT_COLLECTION, id);
            const priorResult = jsonObject(before, "result");
            const priorClaim = priorResult._webhookClaim
                && typeof priorResult._webhookClaim === "object"
                && !Array.isArray(priorResult._webhookClaim)
                ? priorResult._webhookClaim
                : {};
            const history = Array.isArray(priorClaim.history) ? priorClaim.history.slice(-9) : [];
            const priorAttempt = Number(before.get("processing_attempt")) || 0;
            if (priorAttempt || priorStatus === "failed" || priorStatus === "received") {
                history.push({
                    attempt: priorAttempt,
                    status: priorStatus === "failed" ? "failed" : "lease_expired",
                    error: before.getString("error"),
                    claimedAt: before.getDateTime("processing_claimed_at").string(),
                    expiredAt: before.getDateTime("processing_claim_expires_at").string(),
                    completedAt: before.getDateTime("processed_at").string(),
                });
            }
            priorResult._webhookClaim = {
                version: 1,
                retryPolicyVersion,
                attempt: Number(event.get("processing_attempt")) || priorAttempt + 1,
                tokenFingerprint: $security.sha256(token).slice(0, 12),
                workerId,
                claimedAt,
                leaseExpiresAt: expiresAt,
                history,
            };
            event.set("result", priorResult);
            event.set("processing_claim_token", token);
            event.set("processing_claimed_at", claimedAt);
            event.set("processing_claim_expires_at", expiresAt);
            event.set("processing_retry_safe", false);
            event.set("retry_policy_version", retryPolicyVersion);
            txApp.save(event);

            response = {
                claimed: true,
                state: "received",
                claim_token: token,
                attempt: Number(event.get("processing_attempt")) || priorAttempt + 1,
                claimed_at: claimedAt,
                lease_expires_at: expiresAt,
                event: event.publicExport(),
            };
        });
        return e.json(200, response);
    },
    $apis.requireSuperuserAuth(),
);

routerAdd(
    "POST",
    "/api/mantly/support-channel-webhooks/{id}/complete",
    (e) => {
        const id = e.request.pathValue("id");
        const body = e.requestInfo().body || {};
        const token = text(body.claim_token);
        const target = text(body.status).toLowerCase();
        if (!id || !token || ["failed", "processed", "skipped", "unmatched"].indexOf(target) < 0) {
            throw new BadRequestError("invalid_channel_webhook_completion");
        }

        let response = null;
        e.app.runInTransaction((txApp) => {
            const guard = txApp.db().newQuery(
                "UPDATE support_channel_webhook_events SET processing_claim_expires_at = '' "
                + "WHERE id = {:id} AND status = 'received' AND processing_claim_token = {:token}",
            ).bind({ id, token }).execute();

            if (guard.rowsAffected() !== 1) {
                const current = txApp.findRecordById(CHANNEL_EVENT_COLLECTION, id);
                if (
                    current.getString("processing_claim_token") === token
                    && current.getString("status") === target
                ) {
                    response = {
                        completed: true,
                        idempotent: true,
                        state: target,
                        event: current.publicExport(),
                    };
                    return;
                }
                conflict("channel_webhook_completion_fence_conflict");
            }

            const event = txApp.findRecordById(CHANNEL_EVENT_COLLECTION, id);
            const currentResult = jsonObject(event, "result");
            const incomingResult = body.result
                && typeof body.result === "object"
                && !Array.isArray(body.result)
                ? body.result
                : {};
            if (currentResult._webhookClaim) {
                incomingResult._webhookClaim = {
                    ...currentResult._webhookClaim,
                    completedAt: new DateTime().string(),
                    terminalStatus: target,
                };
            }
            event.set("status", target);
            event.set("result", incomingResult);
            event.set("error", text(body.error));
            event.set("processed_at", new DateTime().string());
            event.set("processing_claim_expires_at", "");
            event.set("processing_retry_safe", target === "failed" && body.retry_safe === true);
            const outboundMessageId = text(body.outbound_message_id);
            if (outboundMessageId) {
                event.set("outbound_message", outboundMessageId);
            }
            txApp.save(event);

            response = {
                completed: true,
                idempotent: false,
                state: target,
                event: event.publicExport(),
            };
        });
        return e.json(200, response);
    },
    $apis.requireSuperuserAuth(),
);
