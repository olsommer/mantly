/// <reference path="../../backend/pb_data/types.d.ts" />

/**
 * Transactional outbound-delivery ownership.
 *
 * The external provider call happens after claim and before complete. PocketBase
 * serializes claims; the token fences completion and expired-claim recovery.
 */

routerAdd(
    "POST",
    "/api/mantly/support-delivery/{id}/claim",
    (e) => {
        const delivery = require(`${__hooks}/support_delivery_helpers.js`);
        const id = e.request.pathValue("id");
        const body = e.requestInfo().body || {};
        const issueId = delivery.text(body.issue_id);
        const projectId = delivery.text(body.project_id);
        const tenantId = delivery.text(body.tenant_id);
        const expectedOutboundUpdated = delivery.text(body.expected_outbound_updated);
        const expectedIssueUpdated = delivery.text(body.expected_issue_updated);
        const expectedBodySha256 = delivery.text(body.expected_body_sha256);
        const allowFailed = body.allow_failed === true;
        const workerId = delivery.text(body.worker_id).slice(0, 200);
        const leaseSeconds = Math.max(60, Math.min(1800, Number(body.lease_seconds) || 900));
        if (
            !id
            || !issueId
            || !projectId
            || !expectedOutboundUpdated
            || !expectedIssueUpdated
            || !expectedBodySha256
        ) {
            throw new BadRequestError("missing_delivery_claim_precondition");
        }

        let response = null;
        e.app.runInTransaction((txApp) => {
            // First statement is a write CAS. SQLite serializes competing workers.
            const claim = txApp.db().newQuery(
                "UPDATE support_outbound_messages "
                + "SET status = 'sending' "
                + "WHERE id = {:id} AND updated = {:updated} "
                + "AND (status = 'draft' OR status = 'queued' "
                + "OR ({:allowFailed} = 1 AND status = 'failed'))",
            ).bind({
                id,
                updated: expectedOutboundUpdated,
                allowFailed: allowFailed ? 1 : 0,
            }).execute();

            if (claim.rowsAffected() !== 1) {
                const current = txApp.findRecordById(delivery.OUTBOUND_COLLECTION, id);
                if (current.getString("status") === "sent") {
                    if (
                        current.getString("issue") !== issueId
                        || current.getString("project") !== projectId
                        || (tenantId && current.getString("tenant") !== tenantId)
                    ) {
                        delivery.conflict("delivery_scope_changed");
                    }
                    response = {
                        claimed: false,
                        state: "sent",
                        outbound: delivery.publicRecord(current),
                    };
                    return;
                }
                delivery.conflict("delivery_claim_conflict");
            }

            const outbound = txApp.findRecordById(delivery.OUTBOUND_COLLECTION, id);
            if (
                outbound.getString("issue") !== issueId
                || outbound.getString("project") !== projectId
                || (tenantId && outbound.getString("tenant") !== tenantId)
            ) {
                delivery.conflict("delivery_scope_changed");
            }
            if ($security.sha256(outbound.getString("body")) !== expectedBodySha256) {
                delivery.conflict("delivery_body_changed");
            }

            const issue = txApp.findRecordById(delivery.ISSUE_COLLECTION, issueId);
            if (
                issue.getString("project") !== projectId
                || issue.getString("project") !== outbound.getString("project")
                || (tenantId && (
                    issue.getString("tenant") !== tenantId
                    || issue.getString("tenant") !== outbound.getString("tenant")
                ))
            ) {
                delivery.conflict("delivery_issue_scope_changed");
            }
            if (issue.getDateTime("updated").string() !== expectedIssueUpdated) {
                delivery.conflict("delivery_issue_changed");
            }

            const metadata = delivery.jsonObject(outbound, "metadata");
            if (metadata.approvalRequired === true && metadata.approved !== true) {
                delivery.conflict("delivery_approval_required");
            }
            const unreviewedAutomatic = metadata.source === "agent_answer"
                && metadata.autoSend === true
                && metadata.humanApproved !== true;
            if (unreviewedAutomatic && delivery.issueTerminal(issue)) {
                delivery.conflict("delivery_issue_terminal");
            }

            const token = $security.randomString(32);
            const claimedAt = new DateTime().string();
            const expiresAt = new DateTime(
                new Date(Date.now() + leaseSeconds * 1000).toISOString(),
            ).string();
            const attemptKey = outbound.getString("delivery_attempt_key") || `support-outbound:${id}`;
            metadata.deliveryAttemptKey = attemptKey;
            metadata.deliveryClaimedAt = claimedAt;
            metadata.deliveryClaimedBy = workerId;
            metadata.deliveryCertainty = "in_flight";
            outbound.set("metadata", metadata);
            outbound.set("delivery_claim_token", token);
            outbound.set("delivery_attempt_key", attemptKey);
            outbound.set("delivery_claimed_at", claimedAt);
            outbound.set("delivery_claim_expires_at", expiresAt);
            txApp.save(outbound);

            response = {
                claimed: true,
                state: "sending",
                claim_token: token,
                attempt_key: attemptKey,
                claimed_at: outbound.getDateTime("delivery_claimed_at").string(),
                lease_expires_at: outbound.getDateTime("delivery_claim_expires_at").string(),
                outbound: delivery.publicRecord(outbound),
            };
        });
        return e.json(200, response);
    },
    $apis.requireSuperuserAuth(),
);

routerAdd(
    "POST",
    "/api/mantly/support-delivery/{id}/complete",
    (e) => {
        const delivery = require(`${__hooks}/support_delivery_helpers.js`);
        const id = e.request.pathValue("id");
        const body = e.requestInfo().body || {};
        const token = delivery.text(body.claim_token);
        const target = delivery.text(body.status).toLowerCase();
        const allowed = ["sent", "failed", "queued", "delivery_uncertain"];
        if (!id || !token || allowed.indexOf(target) < 0) {
            throw new BadRequestError("invalid_delivery_completion");
        }
        const certaintyByStatus = {
            sent: "accepted",
            failed: "definitive_failure",
            queued: "retry_safe",
            delivery_uncertain: "uncertain",
        };
        const certainty = delivery.text(body.certainty) || certaintyByStatus[target];
        if (certainty !== certaintyByStatus[target]) {
            throw new BadRequestError("invalid_delivery_certainty");
        }

        let response = null;
        e.app.runInTransaction((txApp) => {
            // Clearing expiry wins atomically against stale-claim reconciliation.
            const guard = txApp.db().newQuery(
                "UPDATE support_outbound_messages SET delivery_claim_expires_at = '' "
                + "WHERE id = {:id} AND status = 'sending' AND delivery_claim_token = {:token}",
            ).bind({ id, token }).execute();

            if (guard.rowsAffected() !== 1) {
                const current = txApp.findRecordById(delivery.OUTBOUND_COLLECTION, id);
                if (
                    current.getString("delivery_claim_token") === token
                    && current.getString("status") === target
                ) {
                    response = {
                        completed: true,
                        idempotent: true,
                        state: target,
                        outbound: delivery.publicRecord(current),
                    };
                    return;
                }
                delivery.conflict("delivery_completion_fence_conflict");
            }

            const outbound = txApp.findRecordById(delivery.OUTBOUND_COLLECTION, id);
            const metadata = delivery.jsonObject(outbound, "metadata");
            const metadataPatch = body.metadata_patch
                && typeof body.metadata_patch === "object"
                && !Array.isArray(body.metadata_patch)
                ? body.metadata_patch
                : {};
            Object.keys(metadataPatch).forEach((key) => {
                if (metadataPatch[key] === null) {
                    delete metadata[key];
                } else {
                    metadata[key] = metadataPatch[key];
                }
            });
            metadata.deliveryCertainty = certainty;
            metadata.deliveryCompletedAt = new DateTime().string();

            outbound.set("status", target);
            outbound.set("provider", delivery.text(body.provider));
            outbound.set("provider_message_id", delivery.text(body.provider_message_id));
            outbound.set("error", delivery.text(body.error));
            outbound.set("metadata", metadata);
            if (target === "sent") {
                outbound.set("sent_at", delivery.text(body.sent_at) || new DateTime().string());
            }
            txApp.save(outbound);

            response = {
                completed: true,
                idempotent: false,
                state: target,
                outbound: delivery.publicRecord(outbound),
            };
        });
        return e.json(200, response);
    },
    $apis.requireSuperuserAuth(),
);

routerAdd(
    "POST",
    "/api/mantly/support-delivery/{id}/reconcile-expired",
    (e) => {
        const delivery = require(`${__hooks}/support_delivery_helpers.js`);
        const id = e.request.pathValue("id");
        const body = e.requestInfo().body || {};
        const expectedExpiresAt = delivery.text(body.expected_expires_at);
        if (!id || !expectedExpiresAt) {
            throw new BadRequestError("invalid_expired_delivery_reconciliation");
        }
        const now = new DateTime().string();
        let response = null;
        e.app.runInTransaction((txApp) => {
            const reconcile = txApp.db().newQuery(
                "UPDATE support_outbound_messages "
                + "SET status = 'delivery_uncertain', delivery_claim_expires_at = '' "
                + "WHERE id = {:id} AND status = 'sending' "
                + "AND delivery_claim_expires_at = {:expectedExpiresAt} "
                + "AND delivery_claim_expires_at <= {:now}",
            ).bind({ id, expectedExpiresAt, now }).execute();
            if (reconcile.rowsAffected() !== 1) {
                const current = txApp.findRecordById(delivery.OUTBOUND_COLLECTION, id);
                if (current.getString("status") === "delivery_uncertain") {
                    response = {
                        reconciled: true,
                        idempotent: true,
                        state: "delivery_uncertain",
                        outbound: delivery.publicRecord(current),
                    };
                    return;
                }
                delivery.conflict("delivery_reconciliation_fence_conflict");
            }

            const outbound = txApp.findRecordById(delivery.OUTBOUND_COLLECTION, id);
            const metadata = delivery.jsonObject(outbound, "metadata");
            metadata.deliveryCertainty = "uncertain";
            metadata.deliveryReconciledAt = now;
            metadata.deliveryReconcileReason = "claim_lease_expired";
            outbound.set("metadata", metadata);
            outbound.set("error", "Delivery outcome uncertain after claim expiry");
            txApp.save(outbound);
            response = {
                reconciled: true,
                idempotent: false,
                state: "delivery_uncertain",
                outbound: delivery.publicRecord(outbound),
            };
        });
        return e.json(200, response);
    },
    $apis.requireSuperuserAuth(),
);
