# Coverage Matrix

This matrix is generated from the canonical coverage ledger. It records source units, activated burdens, audit dimensions, and the saturation audit without treating an absent method as an applicable check.

## Source units

| ID | Unit | Source | Anchors | Type | Status | Findings | Notes |
|---|---|---|---|---|---|---|---|
| `paper` | Complete synthetic manuscript | `SRC-01` | `ANC-01`, `ANC-02`, `ANC-03`, `ANC-100`, `ANC-101`, `ANC-102`, `ANC-103` | section | findings | `LOGIC-01`, `WRT-01` | The fixture contains one short proposition and its interpretation. |

## Source inventory closure

| ID | Canonical object | Source | Type | State | Anchors | Coverage units | Audit | Duplicate of | Reason |
|---|---|---|---|---|---|---|---|---|---|
| `INV-001` | Heading 1 (level 1): A Boundary Case in a Static Signaling Model | `SRC-01` | outline_heading | covered | `ANC-100` | `paper` | — | — | — |
| `INV-002` | Heading 2 (level 2): 1. Setup | `SRC-01` | outline_heading | covered | `ANC-101` | `paper` | — | — | — |
| `INV-003` | Heading 3 (level 2): 2. Result | `SRC-01` | outline_heading | covered | `ANC-102` | `paper` | — | — | — |
| `INV-004` | Heading 4 (level 2): 3. Proposition | `SRC-01` | outline_heading | covered | `ANC-103` | `paper` | — | — | — |

## Activated burden audit

| Burden | Parent | Coverage units | Status | Findings | Notes |
|---|---|---|---|---|---|
| `claim_consistency` | `logical_validity` | `paper` | findings | `LOGIC-01` | The global uniqueness language was compared with the stated equality boundary. |
| `logical_validity` | `logical_validity` | `paper` | findings | `LOGIC-01` | The conclusion does not follow at the equality boundary. |
| `technical_validity` | `technical_validity` | `paper` | findings | `LOGIC-01` | The boundary calculation was checked against the stated payoff comparison. |
| `methodological_validity` | `methodological_validity` | `paper` | checked_no_issue | — | Within the note's stated static domain, the theoretical comparison is an appropriate way to study uniqueness. |
| `writing_mechanics` | `communication_integrity` | `paper` | findings | `WRT-01` | The complete prose was checked sentence by sentence for mechanics and stable wording. |
| `source_support` | `source_support` | `paper` | bounded | — | The literature frontier was assessed but remains bounded by the recorded search scope and source access. |
| `figure_integrity` | `exhibit_integrity` | `paper` | not_applicable | — | The scope anchor confirms that the complete source contains no figure. |

## Audit dimensions

| Dimension | Branch | Status | Findings | Notes |
|---|---|---|---|---|
| `contribution-literature` | universal | bounded | — | The synthetic fixture contains no contribution or literature claims; the audit is bounded to internal logic. |
| `data-provenance-sample` | universal | bounded | — | The synthetic theory fixture contains no data or sample. |
| `measurement-variables` | universal | checked_no_issue | — | The payoff and action objects are defined directly and no constructed measure is used. |
| `identification-assumptions-estimand` | universal | findings | `LOGIC-01` | The equality boundary changes the theoretical object from unique to set-valued. |
| `estimation-computation-inference` | universal | bounded | — | No estimation or computation appears in the synthetic theory fixture. |
| `equations-logic-units` | universal | findings | `LOGIC-01` | The equality boundary contradicts global strict uniqueness. |
| `results-magnitudes-exhibits` | universal | bounded | — | The fixture has one qualitative proposition and no exhibits. |
| `robustness-mechanisms-policy` | universal | bounded | — | These claim types do not appear in the synthetic fixture. |
| `reproducibility-documentation` | universal | checked_no_issue | — | The complete synthetic manuscript source is recorded and fully read. |
| `theory-logic` | theory | findings | `LOGIC-01` | The equality boundary defeats strict uniqueness. |
| `reader-clarity` | universal | findings | `LOGIC-01` | A reader is led to understand uniqueness as global. |
| `claim-consistency` | universal | findings | `LOGIC-01` | The global wording exceeds the boundary result. |
| `terms-variables` | universal | checked_no_issue | — | The equilibrium action and parameter domain are locally defined. |
| `data-limitation-fairness` | universal | not_applicable | — | The synthetic theory fixture uses no data. |
| `review-tone` | universal | checked_no_issue | — | Feedback is neutral, evidence-led, and proportionate. |
| `writing-typography` | universal | findings | `LOGIC-01`, `WRT-01` | The global uniqueness wording needs correction; no typo was found. |
| `language-mechanics` | universal | findings | `WRT-01` | The complete synthetic paragraph was checked for language mechanics. |
| `rendered-table-integrity` | universal | not_applicable | — | No applicable object appears in this synthetic fixture. |
| `partition-regime` | universal | not_applicable | — | No applicable object appears in this synthetic fixture. |
| `measure-algebra` | universal | findings | `LOGIC-01` | The structured analytical or rendered-table audit records the applicable objects. |
| `assumption-implementation` | universal | findings | `LOGIC-01` | The structured analytical or rendered-table audit records the applicable objects. |
| `derived-number-traceability` | universal | not_applicable | — | No applicable object appears in this synthetic fixture. |
| `comparison-harmonization` | universal | not_applicable | — | No applicable object appears in this synthetic fixture. |
| `timing-test-semantics` | universal | checked_no_issue | — | The timing ledger checks the static choice timing and finds no separate timing inconsistency. |
| `availability-exclusivity` | universal | not_applicable | — | No applicable object appears in this synthetic fixture. |
| `economic-argument-chain` | universal | findings | `LOGIC-01` | The payoff ranking supports uniqueness away from equality but not throughout the stated domain. |
| `intervention-comparison-content` | universal | not_applicable | — | The fixture contains no staged intervention, counterfactual, robustness, or compound comparison. |
| `cross-result-coherence` | universal | not_applicable | — | The fixture contains one proposition and no separate results that are linked in the argument. |
| `evidence-object-completeness` | universal | checked_no_issue | — | The payoff comparison and proposition are both reported; no motivated or promised object is omitted. |
| `magnitude-plausibility` | universal | not_applicable | — | The qualitative fixture reports no headline numerical magnitude. |
| `population-claim-transport` | universal | findings | `LOGIC-01` | The proposition transports strict-ranking uniqueness to the equality boundary without a selection condition. |

## Saturation audit

- Required: yes
- Completed: yes
- Saturation reached: yes
- Rejected candidates: 0
- Bounded candidates: 0
- Merged candidates: 0
- New findings: —
- Shortfall or completion note: The fixture is one paragraph with one proposition; a complete saturation sweep found no additional defensible issue.

| Round | Candidate pass | Scope | Coverage units | New findings |
|---|---|---|---|---|
| `SWEEP-01` | `PASS-04` | All in-scope units and active burdens after the initial discovery passes. | `paper` | — |
