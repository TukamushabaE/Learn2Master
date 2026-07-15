# Learn2Master Data Collection Readiness

This release separates technical deployment from authorization to begin dissertation data collection. The live application must not be described as “ready” while any item on `/research/data-collection-readiness` is blocked.

## Required pre-collection checks

1. Confirm `/health` is healthy and `/version` reports the deployed Git commit and current schema migration version.
2. Confirm a real learner can open the assigned first learning outcome without a 500 response.
3. Confirm the teacher can upload an approved document through the configured private Supabase Storage bucket.
4. Review `/research/data-integrity`. The tool is read-only; resolve any correction through an auditable, approved process.
5. Verify coded participants, consent, learner assent and parent consent. Non-learner parent consent must be `Not Applicable`.
6. Verify Physics and ICT learning outcomes contain pre-test, practice and post-test items with the intended concept and competency tags.
7. Complete a pilot sequence: pre-test → recommendation → practice/reflection/practical evidence → post-test → mastery decision.
8. Confirm AI recommendation generated/viewed/followed evidence and teacher oversight records appear in their reports.
9. Pilot learner and teacher questionnaires. A submitted response is final; version the instrument instead of altering an instrument with responses.
10. Export each dataset and confirm filters, participant codes, timestamps and the `research-readiness-v1` dataset-version header.
11. Record external hosting uptime separately. The built-in reliability report measures recorded application events, not provider uptime.
12. Keep the pre-migration database backup and document its hash and restore procedure.

## Ethical and analytic boundaries

- Reports include only active participants with the required consent and assent state.
- Research exports use participant codes, not names or email addresses.
- Pre/post learning gain pairs the first pre-test with the first later post-test for the same learner, learning outcome and study phase.
- A recommendation is “followed” only after a later practice or post-test submission; viewing a page is not follow-through evidence.
- Normalized gain is not applicable where the pre-test is 100. Percentage improvement is not applicable where the pre-test is zero.
- Empty evidence is displayed as “No data yet”; the application does not invent dissertation results.

## Deployment rule

Production deploys run `python manage.py migrate`, an additive, idempotent migration. Demo seeding is disabled in `render.yaml`; never seed demo participants into the actual study database.
