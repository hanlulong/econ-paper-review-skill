# Revision Plan

<!-- review-navigation:start -->
> **Review package:** [Start here](README.md) · [Referee report](report.md) · [Writing report](writing-report.md) · [Revision plan](fix-plan.md) · [Audit trail](evidence/verification.md)
<!-- review-navigation:end -->

Objective: make the paper more publishable for the intended audience by resolving the verified concerns below.

## How to use this plan

Work from P0 to P2 and tick a box when you believe the stated action is complete. A checked box is an author progress marker, not reviewer verification: a later review must compare the revision with the **Done when** condition.

Unless an item says otherwise, the current design can support the stated repair. Items that need new evidence or claim narrowing say so explicitly.

Report comments remain **Pending** until a later review verifies them. In the optional Review Desk, **Open** means not yet addressed; **Ready for recheck** asks for another review; **Challenged** asks the reviewer to reconsider; and **Deferred** keeps the issue open. Notes are optional. Export `review-actions.json` to carry these actions into the next round.

## P0 — essential before submission

### LOGIC-01: The global uniqueness claim fails at the equality boundary

- **Severity:** major
- [ ] **Action:** Add a tie-breaking rule or state a set-valued equilibrium at the boundary. Align Proposition 1, its proof, and the comparative static.
- **Payoff:** Preempts a direct logical objection to the headline proposition.
- **Done when:** Proposition 1 and its proof either supply a tie-breaking rule or state set-valued equilibrium at equality, and the comparative-static summary uses the same boundary qualification.
- **Effort:** hours
- **Dependencies:** None

## P2 — copyediting and optional polish

### WRT-01: The proposition summary has a subject-verb agreement error

- **Severity:** minor
- [ ] **Action:** Replace “characterize” with “characterizes.”
- **Payoff:** Removes an objective grammar error from the proposition summary.
- **Done when:** The proposition summary uses 'characterizes' with the singular subject and no duplicate occurrence remains.
- **Effort:** hours
- **Dependencies:** None
