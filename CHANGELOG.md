# Changelog

Notable changes to the synthetic portfolio system are recorded here. Releases use version tags; this record does not promise a stable public application interface. Historical evidence remains in the linked release notes.

## [Unreleased]

### Changed

- Prepare document metadata, APA Title Case headings, contents lists and a documentation index for review.
- Correct selected-environment loading, model-command configuration, per-vital ordering, blood-pressure freshness and teardown guidance.
- Keep end-to-end reports local and ignored rather than committing them.

### Added

- Prepare prose, metadata and pinned Markdown syntax hooks, their CI setup and real-hook regression samples. The locked local installation and 91-case real-hook verification pass; preparation is not adoption.
- Block commits that leave references to removed functions, classes, config keys, Terraform declarations, dbt models, Airflow task IDs or dependencies, in each commit and over each pushed range in CI. Report unused code (vulture), unused or undeclared dependencies (deptry), unreferenced files and unread `.env.example` entries in warn mode.

## [1.0.1] - 2026-09-17

### Added

- Approved immutable synthetic model artifacts, scheduled scoring and model analytics; see the [release evidence](docs/release-notes-v1.0.1.md). The tag date is Sep 17 2026; the notes record acceptance checks dated Sep 18 2026. Those historical records retain their separate meanings.

## [1.0.0] - 2026-09-17

### Added

- Reproducible synthetic realtime monitoring, governed analytics and guarded infrastructure lifecycle; see the [release notes](docs/release-notes-v1.0.0.md).

[Unreleased]: https://github.com/ian-mungai/healthcare-realtime-monitoring/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/ian-mungai/healthcare-realtime-monitoring/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/ian-mungai/healthcare-realtime-monitoring/releases/tag/v1.0.0
