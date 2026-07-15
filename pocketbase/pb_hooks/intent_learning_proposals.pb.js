/// <reference path="../../backend/pb_data/types.d.ts" />

/** Atomic proposal publish. Active intent learnings change only in this transaction. */

routerAdd(
    "POST",
    "/api/mantly/intent-learning-proposals/{id}/publish",
    (e) => {
        const learning = require(`${__hooks}/intent_learning_proposals_helpers.js`);
        const proposalText = learning.text;
        const proposalJson = learning.jsonValue;
        const proposalStages = learning.stages;
        const proposalHash = learning.proposalHash;
        const activeSetHash = learning.activeSetHash;
        const evalCaseHash = learning.evalCaseHash;
        const feedbackLearningsEnabled = learning.feedbackLearningsEnabled;
        const proposalConflict = learning.conflict;
        const LEARNING_EVAL_POLICY_HASH = learning.LEARNING_EVAL_POLICY_HASH;
        const LEARNING_EVAL_SERVER_FLOOR = learning.LEARNING_EVAL_SERVER_FLOOR;
        const MAX_ACTIVE_INTENT_LEARNINGS = learning.MAX_ACTIVE_INTENT_LEARNINGS;
        const id = e.request.pathValue("id");
        const body = e.requestInfo().body || {};
        const intentName = proposalText(body.intent_name);
        const tenantId = proposalText(body.tenant_id);
        const projectId = proposalText(body.project_id);
        const expectedProposalHash = proposalText(body.expected_proposal_hash);
        const expectedBaseHash = proposalText(body.expected_base_hash);
        const expectedEvalRunId = proposalText(body.expected_eval_run_id);
        const publishedBy = proposalText(body.published_by).slice(0, 200);
        if (
            !id
            || !intentName
            || !projectId
            || !expectedProposalHash
            || !expectedBaseHash
            || !expectedEvalRunId
        ) {
            throw new BadRequestError("missing_learning_publish_precondition");
        }

        let response = null;
        e.app.runInTransaction((txApp) => {
            // First write is the cross-process CAS and SQLite transaction lock.
            const claim = txApp.db().newQuery(
                "UPDATE intent_learning_proposals SET status = 'publishing' "
                + "WHERE id = {:id} AND status = 'evaluated' "
                + "AND proposal_hash = {:proposalHash} "
                + "AND base_learning_hash = {:baseHash} "
                + "AND eval_run = {:evalRunId}",
            ).bind({
                id,
                proposalHash: expectedProposalHash,
                baseHash: expectedBaseHash,
                evalRunId: expectedEvalRunId,
            }).execute();

            if (claim.rowsAffected() !== 1) {
                const current = txApp.findRecordById("intent_learning_proposals", id);
                if (
                    current.getString("status") === "published"
                    && current.getString("intent_name") === intentName
                    && current.getString("project") === projectId
                    && (!tenantId || current.getString("tenant") === tenantId)
                    && current.getString("proposal_hash") === expectedProposalHash
                ) {
                    response = {
                        published: true,
                        idempotent: true,
                        proposal: current.publicExport(),
                    };
                    return;
                }
                proposalConflict("learning_publish_claim_conflict");
            }

            const proposal = txApp.findRecordById("intent_learning_proposals", id);
            if (
                proposal.getString("intent_name") !== intentName
                || proposal.getString("project") !== projectId
                || (tenantId && proposal.getString("tenant") !== tenantId)
            ) {
                proposalConflict("learning_publish_scope_changed");
            }
            if (
                proposal.getString("proposal_hash") !== expectedProposalHash
                || proposalHash(proposal) !== expectedProposalHash
                || proposal.getString("evaluated_proposal_hash") !== expectedProposalHash
            ) {
                proposalConflict("learning_publish_proposal_changed");
            }
            if (
                proposal.getString("base_learning_hash") !== expectedBaseHash
                || proposal.getString("evaluated_base_hash") !== expectedBaseHash
            ) {
                proposalConflict("learning_publish_evaluated_baseline_changed");
            }

            const runbook = txApp.findRecordById(
                "project_intents",
                proposal.getString("runbook_id"),
            );
            if (
                runbook.getString("project") !== projectId
                || runbook.getString("mode") !== "draft"
                || runbook.getString("name").toLowerCase() !== intentName.toLowerCase()
                || runbook.getDateTime("updated").string() !== proposal.getString("runbook_updated")
                || !feedbackLearningsEnabled(runbook)
            ) {
                proposalConflict("learning_publish_runbook_changed");
            }

            const policyHash = proposal.getString("eval_policy_hash");
            const dimension = proposal.getString("eval_dimension");
            const allowedDimensions = ["identity", "intent", "actions", "response"];
            const selectedCaseIdsRaw = proposalJson(proposal, "eval_case_ids", []);
            const selectedCaseIds = Array.isArray(selectedCaseIdsRaw)
                ? selectedCaseIdsRaw.map((value) => proposalText(value)).filter((value) => !!value)
                : [];
            selectedCaseIds.sort();
            const uniqueSelectedCaseIds = selectedCaseIds.filter(
                (value, index) => index === 0 || value !== selectedCaseIds[index - 1],
            );
            const minimum = Number(proposal.get("minimum_score"));
            if (
                policyHash !== LEARNING_EVAL_POLICY_HASH
                || allowedDimensions.indexOf(dimension) < 0
                || selectedCaseIds.length === 0
                || uniqueSelectedCaseIds.length !== selectedCaseIds.length
                || !Number.isFinite(minimum)
                || minimum < LEARNING_EVAL_SERVER_FLOOR
                || minimum > 100
            ) {
                proposalConflict("learning_publish_eval_policy_invalid");
            }

            const run = txApp.findRecordById("eval_runs", expectedEvalRunId);
            if (
                run.getString("status") !== "completed"
                || run.getString("project") !== projectId
                || (tenantId && run.getString("tenant") !== tenantId)
            ) {
                proposalConflict("learning_publish_eval_unavailable");
            }
            const summary = proposalJson(run, "summary", {});
            const total = Number(summary.totalCases) || 0;
            const completed = Number(summary.completedCases) || 0;
            const failed = Number(summary.failedCases) || 0;
            const overall = Number(summary.overallScore);
            if (
                total <= 0
                || completed !== total
                || failed !== 0
                || !Number.isFinite(overall)
                || !Number.isFinite(minimum)
                || overall < minimum
            ) {
                proposalConflict("learning_publish_eval_failed");
            }

            const selectedCases = selectedCaseIds.map((caseId) => {
                const evalCase = txApp.findRecordById("eval_cases", caseId);
                if (
                    evalCase.getString("eval_set") !== run.getString("eval_set")
                    || evalCase.getString("expected_intent_name").toLowerCase()
                        !== intentName.toLowerCase()
                    || !evalCase.getBool("expected_intent_matched")
                    || (dimension === "response" && !evalCase.getString("expected_response").trim())
                ) {
                    proposalConflict("learning_publish_eval_case_invalid");
                }
                return evalCase;
            });
            if (evalCaseHash(selectedCases) !== proposal.getString("eval_case_hash")) {
                proposalConflict("learning_publish_eval_cases_changed");
            }

            const evalResults = txApp.findRecordsByFilter(
                "eval_results",
                "eval_run = {:runId}",
                "created",
                10000,
                0,
                { runId: expectedEvalRunId },
            );
            const scoreField = `${dimension}_score`;
            selectedCaseIds.forEach((caseId) => {
                const result = evalResults.find(
                    (candidate) => candidate.getString("eval_case") === caseId,
                );
                if (!result || result.getString("status") !== "completed") {
                    proposalConflict("learning_publish_eval_coverage_missing");
                }
                const rawScore = result.get(scoreField);
                const score = Number(rawScore);
                if (
                    rawScore === null
                    || rawScore === undefined
                    || rawScore === ""
                    || !Number.isFinite(score)
                    || score < minimum
                ) {
                    proposalConflict("learning_publish_affected_stage_failed");
                }
            });

            const sourceFeedbackId = proposal.getString("source_feedback_id");
            if (sourceFeedbackId) {
                const feedback = txApp.findRecordById("feedback", sourceFeedbackId);
                if (
                    feedback.getString("project") !== projectId
                    || feedback.getString("intent_name").toLowerCase() !== intentName.toLowerCase()
                    || (tenantId && feedback.getString("tenant") !== tenantId)
                ) {
                    proposalConflict("learning_publish_feedback_scope_changed");
                }
            }

            let activeFilter = "intent_name = {:intentName} && project = {:projectId}";
            if (tenantId) {
                activeFilter += " && tenant = {:tenantId}";
            }
            const activeRecords = txApp.findRecordsByFilter(
                "intent_learnings",
                activeFilter,
                "created",
                10000,
                0,
                { intentName, projectId, tenantId },
            );
            if (activeSetHash(activeRecords) !== expectedBaseHash) {
                proposalConflict("learning_publish_active_baseline_changed");
            }

            const operation = proposal.getString("operation");
            const targetId = proposal.getString("target_learning_id");
            let activeLearningId = targetId;
            if (operation === "create") {
                if (activeRecords.length >= MAX_ACTIVE_INTENT_LEARNINGS) {
                    proposalConflict("learning_publish_active_limit_reached");
                }
                const collection = txApp.findCollectionByNameOrId("intent_learnings");
                const active = new Record(collection);
                active.set("intent_name", intentName);
                active.set("learning", proposal.getString("proposed_learning"));
                active.set("source_feedback_id", proposal.getString("source_feedback_id"));
                active.set("affected_stages", proposalStages(proposal));
                if (tenantId) {
                    active.set("tenant", tenantId);
                }
                active.set("project", projectId);
                txApp.save(active);
                activeLearningId = active.id;
            } else if (operation === "update" || operation === "delete") {
                const active = txApp.findRecordById("intent_learnings", targetId);
                if (
                    active.getString("intent_name") !== intentName
                    || active.getString("project") !== projectId
                    || (tenantId && active.getString("tenant") !== tenantId)
                ) {
                    proposalConflict("learning_publish_target_scope_changed");
                }
                if (operation === "update") {
                    active.set("learning", proposal.getString("proposed_learning"));
                    active.set("affected_stages", proposalStages(proposal));
                    if (sourceFeedbackId) {
                        active.set("source_feedback_id", sourceFeedbackId);
                    }
                    txApp.save(active);
                } else {
                    txApp.delete(active);
                }
            } else {
                proposalConflict("learning_publish_operation_invalid");
            }

            proposal.set("status", "published");
            proposal.set("active_learning_id", activeLearningId);
            proposal.set("published_by", publishedBy);
            proposal.set("published_at", new DateTime().string());
            proposal.set("error", "");
            txApp.save(proposal);
            response = {
                published: true,
                idempotent: false,
                proposal: proposal.publicExport(),
            };
        });
        return e.json(200, response);
    },
    $apis.requireSuperuserAuth(),
);
