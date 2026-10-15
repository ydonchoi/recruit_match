# Notion Schema Assessment

- Status: **SCHEMA METADATA REVIEWED / ACCESS AND OPERATING MODEL UNVERIFIED**
- Review date: 2026-10-15
- Scope: database/data-source metadata only; no candidate rows queried and no data changed.

## Sources inspected

- [개인 채용 Registry — Canonical](https://app.notion.com/p/85f6c9342bb343f1aa5d23522a476134)
- [채용분석 Registry](https://app.notion.com/p/3eb2b98a253981fc9574d4ca36f71ff4)
- [00 Candidate Profile Registry](https://app.notion.com/p/74d6cf1a959145e4b865c56605a055df)
- [05 Candidate Evidence Registry](https://app.notion.com/p/fc2fa6b6311948dd91d3600d9526bf42)
- [07 Job Candidate Registry](https://app.notion.com/p/04f3be976c7b42a68077d22dbf721865)

The schema was fetched through the connected Notion integration. The canonical parent page's own fetched content was timestamped 2026-10-09; treat this as observed schema metadata, not proof that every property remains unchanged at implementation time.

## Data-source roles observed

### 1. Canonical opportunity registry

Data source: `collection://382f5aa7-302a-45aa-ae94-e87513fb94e1`

Observed fields include:

- Identity: `Registry ID`, `Opportunity ID`, `Posting ID`, `Organization`, `Position`, `Recruitment Cycle`
- Assessment: `Assessment Ref`, `Eligibility`, `Score`, `Capability Fit`, `Career Fit`, `Compensation`, `Evidence Readiness`, `Critical Unknown`
- Lifecycle and decision: `Lifecycle State`, `Promotion State`, `Recommendation`, `Execution Readiness`, `Execution State`, `Execution Priority`, `Record State`
- Provenance/revalidation: `Decision Source`, `Source Tier`, `Source Run ID`, `Search Combination ID`, `Last Revalidated At`, `Revalidation Status`
- Sync-related: `GitHub Source`, `Notion Sync State`

**Implication:** the schema already represents most opportunity-lifecycle and assessment concepts. The existence of GitHub-related properties does not establish that a GitHub mirror is required. They should be treated as legacy/compatibility fields until their current purpose is demonstrated. Do not build GitHub CRUD or sync merely to populate them.

### 2. Candidate Profile Registry

Data source: `collection://df5197c8-fbab-4397-8bff-16e17dbb7f2c`

Observed fields include `Candidate ID`, `Name`, `Preferred Region`, `Minimum Compensation`, `Target Compensation`, `Verification Status`, `Version`, `Source Reference`, and `Last Verified`.

These fields are candidate-linked personal/contextual data. Retain only fields needed for the stated matching purpose. Workspace-level access and retention controls were not verified.

### 3. Candidate Evidence Registry

Data source: `collection://d1de2d7e-abb5-477e-b0ae-6c747ec58fad`

Observed fields include `Candidate ID`, `Capability`, `Achievement`, `Evidence`, `Source`, `Source Type`, `Evidence Type`, `Evidence Status`, `Verification Status`, `Version`, and verification time.

This is evidence metadata and may itself be sensitive when linked to a candidate. Do not upload original files or unnecessary details into GitHub; evidence references must not be treated as proof that the referenced source was verified.

### 4. Job Candidate Registry

Data source: `collection://2ace59d2-8af0-4886-8ce1-0de8dc3d65b4`

Observed fields include `Job ID`, `Position`, `Source URL`, `Mandatory Result`, `Decision Score`, `Compensation M`, `Comp Confidence`, `Region`, `Posting Date`, and `Verification`.

This appears job/posting-oriented from its field names. Confirm whether it duplicates the canonical opportunity registry before choosing one canonical identity source.

## Data-model observations

1. **Logical separation exists at the data-source level:** opportunity registry, candidate profile, candidate evidence, and job candidate records are separate data sources.
2. **Foreign-key integrity is not established by the schema alone:** `Candidate ID` and several identity fields are plain text. Uniqueness, referential integrity, deletion propagation and duplicate behavior require explicit contracts.
3. **State vocabularies are mixed:** some fields are Select properties with enumerated options, while others are plain text. For text fields, the allowed values and transition rules are not enforced by the property type.
4. **UNKNOWN is represented in some fields but not uniformly enforced:** for example, Evidence Readiness has an UNKNOWN option; fields such as Eligibility and Recommendation are text. A domain adapter must validate values and must never infer PASS/ACTIVE/PROMOTED from an empty property.
5. **Legacy sync properties exist:** `GitHub Source` and `Notion Sync State` should not be populated by new code unless a concrete supported workflow requires them.
6. **Privacy controls are unverified:** database separation is not proof of distinct permissions. The actual workspace, database, integration and user access controls were not inspected.

## Existing legacy adapter mismatch

The inspected `registry/notion_registry.py` maps a subset of fields: Registry ID, Opportunity ID, Organization, Position, Recruitment Cycle, Posting ID, Assessment Ref, Promotion State, Lifecycle State, Execution State, Revalidation Status, Last Revalidated At, Source Run ID, Search Combination ID, Job Axis, and Organization Type.

It does not map all observed schema fields, including Eligibility, Score, Recommendation, Execution Readiness, Execution Priority, Evidence Readiness, Decision Source, Source Tier, GitHub Source and Notion Sync State. The legacy adapter therefore should not be copied as if it were a complete canonical schema mapping. This is a code/schema comparison, not a live write test.

The legacy adapter also has separately documented hazards: incomplete pagination on one lookup path, first-match updates on duplicate matches, success-shaped defaults for missing state, and hardcoded quality flags. These must not be carried forward.

## Decision

- **GitHub registry create/update/delete and GitHub registry sync:** do not implement by default.
- **Notion as canonical opportunity store:** plausible, but not approved for writes yet.
- **Candidate profile/evidence storage:** use only after field-by-field minimization, access-control and retention review.
- **Target adapter:** implement only after the domain model, state vocabularies, stable IDs, uniqueness/conflict behavior, access model and required read/write workflows are agreed.
- **No data migration or deletion:** this review only inspected schema metadata. It did not read rows, move data, delete data or establish historical erasure.

## Required next checks before a write adapter

1. Confirm current schema and property types immediately before implementation.
2. Determine whether `Job Candidate Registry` is duplicate, view, or independent canonical data.
3. Define stable IDs and uniqueness rules for opportunities, postings, candidate IDs and evidence records.
4. Decide whether candidate-linked data should remain in the same workspace and verify actual permissions.
5. Define field purpose, source, necessity, retention and deletion behavior.
6. Define strict state vocabularies and transition rules for text-based state fields.
7. Define pagination, duplicate resolution, conflict detection, rate limits, retries, idempotency and read-back reconciliation.
8. Add synthetic-only tests for missing properties, invalid states, duplicate IDs, stale updates, privacy boundaries and partial external failure.
9. Enable writes only after test results and an explicit review record exist.
