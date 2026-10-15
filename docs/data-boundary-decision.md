# Data Boundary and Registry Persistence Decision

- Status: **TARGET ARCHITECTURE DECISION — NOTION SCHEMA REVIEW REQUIRED**
- Date: 2026-10-15

## Decision

1. **Candidate personal data, candidate-specific registry records, and candidate-linked assessments must not be stored in GitHub.** This includes source files, issues, PR text/comments, branches, commits, CI logs/artifacts, fixtures and generated reports.
2. **Do not implement GitHub Registry create/update/delete operations or a GitHub registry-sync stage by default.** Current disposition: NOT IMPLEMENTED / OUT OF SCOPE unless a future explicit architecture review proves a necessary use case that cannot be met by the approved private store.
3. GitHub remains for source code, non-sensitive contracts/policies, synthetic tests and sanitized technical documentation. A private repository is not a reason to put personal data there.
4. Notion is a candidate registry store because the legacy system already has a Notion adapter and the user explicitly asked to consider Notion DB modeling. **Notion is not automatically approved**: schema, workspace access, integrations, retention and field necessity must be reviewed before any candidate-data write.
5. The analysis pipeline remains in scope. Removing the GitHub registry sink does not remove search, source verification, attachment inspection, evidence mapping, eligibility, fit, compensation, ranking, recommendation, revalidation or the logical Registry domain.

## Rationale

The legacy architecture separates Registry Write, GitHub Registry Sync and application execution. They are distinct responsibilities; their presence in the old pipeline is not sufficient reason to reproduce them.

The active legacy instruction prohibits sensitive original evidence in the repository and requires minimum necessary candidate facts and evidence references. GitHub registry synchronization would create another copy and consistency boundary, increasing duplication, access-control, deletion, audit and reconciliation obligations without a demonstrated requirement.

If the approved Notion database can support the needed private registry workflows, a GitHub mirror is redundant. This is a design inference pending review of the actual Notion schema and user workflow, not a claim that the current Notion DB already meets every requirement.

## Data placement

| Data class | GitHub | Approved private store |
|---|---|---|
| Source code, non-sensitive policy and architecture | Allowed, after secret/PII review | Optional |
| Synthetic test fixtures | Allowed; must be synthetic | Not required |
| Public job posting URL/facts | Default: do not persist per-run records in repo | May be referenced with provenance |
| Candidate profile, preferences and capability summary linked to a person | Prohibited | Only minimum necessary fields after review |
| Original documents, identity/contact details, full forms, certificates/transcripts | Prohibited | Do not upload by default; prefer independently controlled source references |
| Candidate-to-job assessment, ranking, recommendation, application outcome | Prohibited | Only if necessary and approved by minimization review |
| Tokens, cookies and credentials | Prohibited | Approved secret/credential mechanism only |

## Proposed logical boundary

- **Analysis runtime:** process transient source material and minimum candidate facts; avoid persistent local/GitHub copies by default.
- **Canonical registry:** an approved private database. Notion is a candidate only after schema/access review.
- **Evidence:** retain source references, timestamps and hashes where appropriate; do not copy sensitive original bytes.
- **GitHub:** implementation and verification artifacts only, with synthetic data.
- **Audit trail:** record state transitions and execution evidence without embedding personal data; use opaque identifiers where possible.

No live Notion writes are authorized by this document.

## Notion schema review required before adapter implementation

Confirm support for:
- stable record ID and stable opportunity/posting identity;
- separate candidate, opportunity and recruitment-cycle records;
- requirement-level evidence references without storing original sensitive files;
- independent lifecycle, application outcome, execution readiness, recommendation and revalidation states;
- source URL/type, retrieval and verification timestamps, provenance and uncertainty;
- explicit UNKNOWN/unverified states without defaults to ACTIVE/PROMOTED/PASS;
- duplicate detection, conflict handling, pagination and schema-version checks;
- access control, ownership, retention/deletion and auditability;
- rate limits, retry policy, idempotency and read-back/reconciliation.

If the schema cannot safely represent a required state, redesign it or select another approved store before enabling writes. Do not coerce incompatible fields into success-shaped defaults.

## Legacy cleanup

This decision applies to the new repository. It does not delete records from the legacy repository, rewrite Git history or remove existing Notion data. Legacy cleanup requires a separate inventory, explicit scope, impact review and history-remediation assessment. Deleting a working-tree file is not proof that historical copies are erased.

## Acceptance criteria

- No GitHub registry CRUD/sync adapter or pipeline stage by default.
- No real candidate data in repo code, docs, tests, issues, PRs, logs or CI artifacts.
- Tests use synthetic records and check privacy boundaries.
- Notion writes remain blocked until schema/access review is recorded.
- Any proposed exception requires an explicit decision record, data-minimization assessment, access design and tests proving sensitive candidate data is not copied to GitHub.
