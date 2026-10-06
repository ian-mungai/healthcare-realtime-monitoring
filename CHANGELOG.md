# Changelog

Notable changes to the synthetic portfolio system are recorded here. Releases use version tags; this record does not promise a stable public application interface. Historical evidence remains in the linked release notes.

## [Unreleased]

### Changed

- Deployment fixes from the Oct 6 2026 first deployment. The deploy user's Glue template allows tagging the Glue job; the EC2 template allows reading security group rules. `run_fhir_setup.sh` reads the seed bundle prefix from the setup task definition, because the targeted foundation apply does not record that output. The simulator's blood-pressure readings are exported from the current Synthea cohort; the quickstart says to export them before pushing images.
- Adopt Conventional Docs for authored project Markdown after complete document and workflow review. Correct metadata, American Psychological Association (APA) Title Case headings, contents, terminology, procedure anatomy, source provenance and recorded verification boundaries; preserve historical evidence and the separate README structure.
- Correct selected-environment loading, model-command configuration, per-vital ordering, blood-pressure freshness and teardown guidance.
- Select each patient's less frequent tagged simulator scenario for runs planned to cover the full 30-minute window. Ties and short runs use a seed or random choice; startup tags do not replace analytical window, class and leakage checks.
- Ignore isolated load-test events in the live dashboard. Close ordinary subscribers for a consistent measurement baseline because their shared WebSocket connections still receive events.
- Preserve the first load-runner failure when cleanup also fails, bound WebSocket shutdown and report sanitized failure categories, accepted writes and missing observations.
- Keep end-to-end reports local and ignored rather than committing them.

### Fixed

- Handle the GitHub OpenID Connect (OIDC) provider and deployment-role outputs when a refresh-only plan sees no application-stage resources. Remove the unused Fast Healthcare Interoperability Resources (FHIR) seed-prefix outputs; the setup runner reads the task definition.
- Verify processor write health and actual write denial before replay submission. Remove the run's temporary Deny policy and verify processor writes during cleanup, then remove only owned terminal messages after a bounded quiet interval. The original deployed replay and load failures still require fresh live verification.

### Added

- Add prose, metadata and pinned Markdown syntax hooks, their continuous integration (CI) setup and real-hook regression samples. The locked installation and 91-case real-hook verification passed at `034488c`; the adoption review also checks the ignored private guide explicitly. Permit only `details` and `summary` for collapsed historical context while retaining the other Hypertext Markup Language (HTML) syntax guard.
- Block commits that leave references to removed functions, classes, config keys, Terraform declarations, dbt models, Airflow task IDs or dependencies, in each commit and over each pushed range in CI. Report unused code (vulture), unused or undeclared dependencies (deptry), unreferenced files and unread `.env.example` entries in warn mode.
- Add dbt-project-evaluator 1.4.0, locked with dbt_utils 1.4.1 and disabled unless a run opts in. Add an Airflow DagBag test for import errors, unused task IDs and unwired tasks.
- Install every pipeline stage from a hash-pinned lock compiled from its `.in` source: the development environment, the Airflow package, the dbt, Soda and simulator images and the Glue job. The Glue job now pins `s3fs`, which had no version. `tools/compile_requirements.py` recompiles the locks in Linux containers and a `requirement-locks` hook keeps each lock in step with its source.

## [1.0.1] - 2026-09-17

### Added

- Approved immutable synthetic model artifacts, scheduled scoring and model analytics; see the [release evidence](docs/release-notes-v1.0.1.md). The tag date is Sep 17 2026; the notes record acceptance checks dated Sep 18 2026. Those historical records retain their separate meanings.

## [1.0.0] - 2026-09-17

### Added

- Reproducible synthetic realtime monitoring, governed analytics and guarded infrastructure lifecycle; see the [release notes](docs/release-notes-v1.0.0.md).

[Unreleased]: https://github.com/ian-mungai/healthcare-realtime-monitoring/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/ian-mungai/healthcare-realtime-monitoring/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/ian-mungai/healthcare-realtime-monitoring/releases/tag/v1.0.0
