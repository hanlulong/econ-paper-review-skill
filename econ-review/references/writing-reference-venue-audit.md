# Writing and Venue Audit

Use this protocol in every full review. Activate journal fit only when the user explicitly requests venue analysis, and record that request canonically as `journal_fit` in `run.json.requested_addons`; record an empty array when no add-on was requested. Keep language mechanics, substantive clarity, and any requested journal fit distinct. A polished paragraph can contain a substantive overclaim; a technically correct paragraph can still contain grammar or usage errors. Literature positioning and whether a named source supports a load-bearing claim belong to substantive review, not the editing comments.

## 1. Language mechanics pass

Read the complete manuscript sentence by sentence and separately check:

- grammar and syntax;
- article usage (`a`, `an`, `the`, and zero article);
- subject-verb and singular-plural agreement;
- tense, voice, and author perspective;
- pronouns, antecedents, and comparison structure;
- prepositions and idiomatic usage;
- spelling, capitalization, punctuation, and possessives;
- hyphenation and compound modifiers;
- sentence fragments, run-ons, parallelism, and modifier placement;
- internal cross-references, numbering, bibliography-style consistency, and objective typographical errors;
- exhibit range and referent integrity: prose column/panel ranges must match rendered cardinality, and labels such as `same`, `other`, `baseline`, or `reference` must say what they are relative to when the referent is not visually local and unambiguous.

Do not put citation accuracy, source support, missing literature, or reference-record verification in the editing comments. Those are substantive evidence checks and belong in the literature/source ledger and substance findings. The writing pass may correct only mechanical bibliography presentation that can be established from the manuscript itself, such as inconsistent author-year punctuation or a visibly broken cross-reference.

Check the rendered PDF before retaining errors that may come from line wrapping, OCR, ligatures, mathematical extraction, source commands, or soft hyphens. Record render verification for each occurrence, not only for the aggregate group. Mark extraction-only candidates `refuted` when the rendered page is correct and omit them from author-facing comments while retaining the disposition reason. Aggregate repeated mechanical errors by correction rule and source provenance while listing every verified location; do not mix unrelated grammar, capitalization, terminology, and substantive-consistency defects into one omnibus row.

Article usage deserves an explicit pass because it is easy to miss and often systematic. Check whether a noun is countable, whether it is introduced or already identified, whether a unique institutional object needs `the`, and whether general categories correctly take zero article. Correct only genuine usage errors; acceptable variation across dialects is not a finding.

## 2. Language-consistency pass

Create consistency groups for:

- economic objects and constructed variables;
- group, population, geographic, and sample labels;
- shock, treatment, benchmark, counterfactual, and horizon language;
- causal, predictive, descriptive, mechanism, welfare, and policy verbs;
- capitalization, spelling, hyphenation, abbreviations, and notation variants;
- tense and perspective across coauthored sections;
- table, figure, appendix, and section naming conventions.

Choose a preferred form based on the exact economic object, not on stylistic taste. A variant is harmless when it cannot change interpretation. If variants change scope, unit, population, or evidentiary strength, connect the consistency item to the claim and term ledgers.

## 3. Economics-writing style pass

Apply reader-first economics guidance conditionally:

- put the question, economic object, central result, benchmark, and contribution early;
- lead paragraphs with their point and give each paragraph one job;
- prefer active, concrete, present-tense prose when the actor matters;
- shorten throat-clearing, travelogue, repeated previews, vague transitions, and literature lists;
- use tables and figures as grammatical subjects;
- state magnitudes in interpretable units and relative to a benchmark;
- distinguish observed facts, estimates, assumptions, simulations, and interpretations;
- keep mechanisms and policy implications at the level the design supports;
- make the abstract, introduction, conclusion, and main exhibits mutually consistent without requiring verbatim repetition.

Style suggestions must identify the passage's current job, why the organization or wording obstructs that job, and a concrete revision pattern or replacement sentence. Mark them optional unless they affect interpretation, contribution, or the journal-facing argument. Do not enforce a single voice or ban passive constructions mechanically.

Build a section-by-section reader audit appropriate to the paper rather than a universal template. Give credit for sections already doing their job. For each relevant section, record its current job, what works, the remaining reader friction, and the highest-return revision direction. Typical questions include whether the title names the object, the abstract gives the answer and interpretable magnitude, the introduction establishes question-answer-contribution without repetition, results paragraphs lead with results, exhibits are self-contained, and the conclusion synthesizes rather than re-advertises. Adapt these questions for theory, structural, macro, descriptive, experimental, and mixed papers.

Create a redundancy map for repeated framing, contribution, result, mechanism, and implication passages. Repetition becomes a finding only when it imposes real search cost, dilutes the evidence hierarchy, or creates inconsistency. Identify the best home for the idea and preserve useful recaps.

## 4. Optional journal-fit and submission-strategy audit

Run this section only when the user explicitly requests it. Journal fit is a dated match among audience, contribution bar, evidence standard, and article format—not a prestige label or acceptance prediction. Use current official aims/scope and submission guidance plus recent closely related publications.

When a venue or tier is named or assessable and current literature access exists, provide 3–6 candidate journals. For each candidate, record:

- dated official scope evidence;
- 1–2 recent comparator papers verified with URL/DOI and access date;
- the paper's current fit and concrete mismatch;
- the empirical, theoretical, computational, or policy evidence standard currently met versus still needed;
- verifiable format constraints when relevant;
- the revisions that would change the fit assessment.

End with an ambitious-to-safe submission sequence and distinguish as-is fit from fit after named feasible revisions. Use qualitative categories only (`stretch after major revision`, `credible target after revision`, `credible current-scope target`, or `poor fit`). Never invent acceptance probabilities. If the venue is unspecified or live search is unavailable, state the plausible contribution/evidence bar and mark specific fit `bounded` or `not_assessed`.

## 5. Required outputs and report routing

Write `evidence/writing.json` and a readable `evidence/writing.md`. Record the activated reader tasks, writing strengths, section audit, redundancy map, checked mechanics, consistency groups, and concrete style suggestions. Populate venue candidates only for an explicitly requested venue audit. Each mechanics group records every verified occurrence, correction, reader consequence, priority, render state, and source provenance. Every adverse mechanics, consistency, or requested-venue state that materially affects a report must map to an active finding. Record checked-clean groups as well as problems. Do not infer the writing scope from a single paper-type label; theory, empirical evidence, institutional description, computation, and policy interpretation may coexist in one section.

For current contract-v0.4 full runs, surface this audit in `editing-comments.md`. Writing-audit schema v0.4 is canonical input to this full-mode structure:

- `## Editing assessment`, including specific strengths and overall priority;
- `## Highest-return editing revisions`, linked concisely to finding IDs;
- `## Section-by-section reader audit`;
- `## Terminology, definitions, and notation`;
- `## Tables and figures as writing`;
- `## Mechanics and copyedit inventory`, separating main text from instruments or reproduced materials;
- `## Style and writing improvements`, including the redundancy map;
- `## Detailed Editing Comments (N)`.

The author-facing writing capacity is 30 verified comments. It is not a target or a reason to stop the sentence-by-sentence pass. Aggregate repeated occurrences only when they share one correction rule and consequence, while listing every material location. If more than 30 independently defensible writing findings survive, preserve them and pause completion for explicit user resolution rather than suppressing them.

Report-contract and writing-audit versions are independent. Current full packages use writing-audit schema v0.4 and generate every core preamble section from `evidence/writing.json`; an existing Markdown preamble is never canonical input. Legacy report, writing-audit, and receipt packages remain valid under their declared versions. Keep summary sections concise and put the complete correction inventory in the audit ledger so the same diagnosis is not repeated. Never add an author-facing `Assessment Boundary` section; retain scope details in canonical evidence and the audit trail.

Route mechanics, article usage, language consistency, exhibit presentation, and optional style to the writing channel. Route unclear or misleading expression at load-bearing points and source-support failures to substance. The editing comments must distinguish objective corrections from optional style improvements.

When journal fit is explicitly requested, add `journal_fit` to `run.json.requested_addons`, populate `venue_fit` as `assessed` or `bounded`, and generate `## Journal fit and submission strategy` in `editing-comments.md`, never in the substance report. Official-scope and comparator links must use HTTPS, and their evidence dates cannot exceed the recorded assessment date or current date. Without that flag, use `venue_fit.status: not_requested`, retain no dated/candidate/finding payload, and emit no journal-fit section. Quick mode creates the editing comments only when writing-channel findings exist or the user explicitly requests writing analysis. Contract v0.1 keeps its legacy output placement.

Every current source-derived writing row must cite the coverage units it audits and canonical evidence that supports it. Bind each retained mechanics occurrence to an exact or normalized-transcription anchor. Use a scope anchor with `purpose: checked_absence` for checked-clean mechanics groups and terminology groups marked consistent. Adverse rows may use `finding_evidence` only when it belongs to an active, verification-passed finding; do not treat a prose locator as source proof.
