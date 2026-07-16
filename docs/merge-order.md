# Production-hardening PR merge order

This repository uses an ordered PR stack for the pilot-readiness programme.
Every PR targets `main`, but each implementation branch is created from the
preceding branch so later PRs contain the complete validated state.

Merge in this order:

1. V1 scope contract — closes #2
2. Pilot success criteria and KPI contract — closes #1
3. Security baseline and incident procedures — closes #3
4. CI and repository quality contract — closes #4
5. Backup, restore, and disaster recovery — closes #5
6. DACH privacy and compliance package — closes #7
7. Pilot evidence tooling and execution package — repository portion of #6
8. Production observability and operational runbooks — closes #9
9. Scalability limits and architecture evolution path — closes #8
10. Mantly naming and package metadata cleanup — closes #10
11. Licensing and source-distribution decision package — repository portion of #11

## Merge policy

- Use merge commits or rebase merges for the ordered stack. Avoid squashing a
  middle PR while later branches still depend on its individual commits unless
  the later branches are refreshed first.
- Do not merge a later PR while an earlier PR in the stack is unmerged.
- After each merge, update the next branch from `main` before final approval if
  GitHub reports drift or checks were evaluated against an older base.
- The roadmap epic (#12) is the status source of truth.
- External outcomes that cannot be completed in source control — a real
  design-partner pilot and legal review of license/DPA terms — remain open until
  evidence is attached.
