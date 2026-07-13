# Editorial Synthesis

Synthesize only verified, surviving findings. Do not use synthesis to create new concerns.

Under the current contract, create `synthesis.json` and a cohesive referee opening from verified substance findings. Separate technical severity from decision relevance and repairability. Writing-channel findings are synthesized separately in `writing-report.md`. If a writing problem obscures the science, changes an estimand or claim, or exposes unsupported load-bearing source use, reclassify it as substance before synthesis. Legacy contracts retain their documented presentation.

Synthesis is a projection of canonical evidence, not a new evidence layer. Link each strength, assessment statement, posture rationale, convincingness judgment, concern rationale, and upgrade condition to the claim IDs, finding IDs, and evidence IDs that support it. A strength must be source-grounded just as a criticism is. If a sentence cannot be linked, narrow it, mark it bounded, or remove it.

The synthesis should leave the author with a better paper, not merely a verdict. Explain which assets to preserve, which changes have the highest return, and why the minimum repair improves the central argument. Do not equate rigor with maximal workload.

## 1. Rank by decision relevance

For each finding, ask:

1. Does it affect the central claim, credible interpretation, contribution, or reproducibility?
2. How likely is it to matter at the stated venue or tier?
3. Is it fixable within the paper's design and a plausible revision cycle?
4. What is the smallest decisive repair?
5. Would the finding remain after the strongest plausible author reply?

Record the answer through linked canonical IDs rather than unsupported free text. Principal concerns may group findings, but may not silently add a new diagnosis or amplify a bounded one into a verified defect.

For data-related concerns, rank the consequence for the paper's actual bounded claim, not the imperfection of the dataset in the abstract. An inherent limitation that is disclosed and claim-calibrated is not a weakness. If claim narrowing fully resolves the concern, severity follows from where and how strongly the overclaim appears, not from the unavailable ideal data.

Group shared root causes into principal concerns. Count the root-cause concern once in the headline tally even when it is supported by several findings or appears in many manuscript locations; occurrence count is evidence about scope, not a mechanical severity multiplier. A concise referee synthesis will normally have one to three principal concerns, but this is an editorial norm rather than a validator cap. Preserve every independently or cumulatively dispositive concern.

## 2. Separate buckets

- **Potentially dispositive:** could justify rejection if unresolved. State the affected central claim and repairability.
- **Posture material:** could change the recommendation independently or cumulatively.
- **Revision value:** a verified improvement with a realistic repair path that does not determine the posture.
- **Minor:** useful polish or clarification. Mark objective grammar, notation, and factual corrections as required polish; mark preference-based style alternatives as optional. Never hold the paper hostage over this bucket.

Do not repeat the same underlying issue across buckets.

### Calibration examples: what is not a major issue

- A disclosed data limitation paired with claims that remain inside that limitation is not an active criticism.
- A missing conventional diagnostic is not a finding when the reconstructed design does not activate the diagnostic or when it cannot change the paper's claim.
- Repeated instances of one terminology or reporting error normally form one root-cause finding, not one major issue per occurrence.
- A local typo or optional stylistic preference is writing-channel polish unless it changes a scientific object, claim, or interpretation.
- A feasible robustness check that would merely repeat evidence already decisive for the stated claim is optional strengthening, not posture material.

These examples calibrate decision relevance, not coverage. Retain every independently useful verified correction in the appropriate detailed inventory.

## 3. Calibrate without false precision

Use broad qualitative tiers across contract versions:

- **Top general-interest:** unusually important question and clear value beyond the closest frontier, with exceptionally credible execution.
- **Leading field:** meaningful field contribution, strong execution, and relevance beyond a narrow setting.
- **Standard field/general:** sound, useful, and appropriately positioned contribution with correct claims and adequate transparency.
- **Regional/specialized:** credible contribution whose audience or external scope is narrower.

Treat these as qualitative bars, not acceptance probabilities. The substance report may use a user-supplied venue or broad tier to calibrate posture. Add candidate-journal recommendations and submission sequencing to `writing-report.md` only when the user explicitly requests venue analysis. If venue analysis is not requested, do not add a placeholder section.

## 4. Write the referee opening

Use this order:

1. `Overall assessment`: question, approach, evidence, answer, verified contribution, and specific strengths.
2. `Recommendation and main grounds`: assessment, rationale, repairability, and upgrade conditions.
3. `Issues that could prevent publication`: principal concerns mapped to active findings.
4. `Other major issues`: every posture-material finding not already grouped above.
5. `Is the argument convincing?`: which links work, which remain provisional, and what would change the assessment.

Do not imitate any one journal's stock opening or word limit. The transferable standard is accurate reconstruction, decisive prioritization, constructive specificity, and a clear claim-evidence judgment.

## 5. Set a posture

Use:

- `Reject`: one or more essential problems are not realistically repairable within the present design, or the contribution falls materially short of the target bar.
- `Weak R&R`: substantial uncertainty remains, but a specified revision could produce a publishable paper.
- `Strong R&R`: the paper is promising and the remaining essential work is clear and feasible.
- `Accept`: no essential or major issue remains; use rarely in pre-submission review.

Call this a review posture, not a prediction or decision. State what evidence or revision would upgrade it.

## 6. Apply the signature test

Ask: flaws and all, is there a real paper here that advances understanding? State what is genuinely strong. Do not use a token compliment; identify the actual asset, insight, design, data, or result worth preserving.

## 7. Enforce publication value

For every requested change, record:

- the objection it resolves;
- the paper locations affected;
- the minimum decisive analysis or edit;
- likely effort and dependencies;
- why the change improves validity, interpretation, contribution, or venue readiness.

Delete recommendations that add work without changing any evaluation.
