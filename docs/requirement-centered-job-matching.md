# Requirement-centered job matching model

This module evaluates a job's explicit requirements against source documents on demand. It does **not** create or persist a normalized applicant profile.

## Flow

1. Define a list of `JobRequirement` objects for a job.
2. Keep resumes and supporting materials as `SourceDocument` objects.
3. Call `retrieve_evidence_on_demand(requirement, documents)` when a requirement needs review.
4. Make a criterion-level `CriterionDecision` with score, status, evidence references, counter-evidence references, rationale, and uncertainty notes.
5. Call `build_evaluation_run(...)` to produce a run-scoped payload containing criterion results, source excerpts, coverage, eligibility status, and limitations.

See `tests/test_job_matching_model.py` for executable examples.

## Evaluation semantics

- Scores are in the range 0–5. The aggregate score is a weighted mean rescaled to 0–100 over criteria with usable cited evidence.
- Missing or unresolvable evidence does not become a zero score.
- `evidence_coverage` is the sum of weights for criteria with supported decisions divided by the total requirement weight.
- Eligibility is a separate status (`PASS`, `FAIL`, `HOLD`, or `NOT_APPLICABLE`) and is never inferred from fit score.
- An evidence reference must resolve to a snippet retrieved for the evaluation run before it can contribute to the score.
- `ASSESSED`, `PROVISIONAL`, `UNASSESSED`, `CONFLICTED`, and `INVALID_INPUT` are evaluation states, not candidate classifications.

## Limitations

The initial retrieval implementation is deterministic keyword overlap across sentence-sized excerpts. It can miss paraphrases and semantic matches; it does not verify source authenticity, truth, or whether a cited excerpt genuinely supports the assigned score. A human or separately validated assessment service must supply criterion decisions. This is a baseline model, not an empirically calibrated hiring predictor. Do not use demographic or other protected characteristics as fit criteria.

## Current integration boundary

The model is invoked for one user-selected posting by `interactive_workflow.py`. Requirements and candidate material are held in process memory; criterion decisions are entered by the user after reviewing retrieved snippets. The resulting evaluation, excerpts, and recommendation are returned to the active session and are not written to the repository. Recommendation requires eligibility `PASS`, a user-configured overall score threshold, and no assessed mandatory criterion below 3/5. These are transparent initial rules, not an empirically calibrated predictor. The initial retrieval remains deterministic keyword overlap. Long-term application tracking requires a separate approved secure store and is not implemented here.
