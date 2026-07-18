export type IssueRequestGuard = {
    requestedIssueId: string;
    activeIssueId: string;
    requestEpoch: number;
    activeEpoch: number;
};

export type IssueRequestToken = {
    requestedIssueId: string;
    requestEpoch: number;
};

export type IssueMutationGuard = {
    requestedIssueId: string;
    activeIssueId: string;
    ownerGeneration: number;
    activeOwnerGeneration: number | undefined;
};

export function shouldApplyIssueRequest({
    requestedIssueId,
    activeIssueId,
    requestEpoch,
    activeEpoch,
}: IssueRequestGuard): boolean {
    return Boolean(requestedIssueId)
        && requestedIssueId === activeIssueId
        && requestEpoch === activeEpoch;
}

export function shouldApplyIssueMutation({
    requestedIssueId,
    activeIssueId,
    ownerGeneration,
    activeOwnerGeneration,
}: IssueMutationGuard): boolean {
    // Fetch epochs intentionally do not participate here: same-ticket polling may
    // start while an action runs. Ticket identity plus action ownership rejects
    // A -> B writes without discarding a valid action result for A.
    return Boolean(requestedIssueId)
        && requestedIssueId === activeIssueId
        && ownerGeneration === activeOwnerGeneration;
}
