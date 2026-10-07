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

- Read the BIDMC SpO2 channel when a record's header puts format fields before the signal name (bidmc19n); records past 10 were never fetched before the 100-patient cohort.
- Handle the GitHub OpenID Connect (OIDC) provider and deployment-role outputs when a refresh-only plan sees no application-stage resources. Remove the unused Fast Healthcare Interoperability Resources (FHIR) seed-prefix outputs; the setup runner reads the task definition.
- Allow the realtime processor to publish metrics to the `HealthcareRealtime/LoadTest` namespace; load-test metrics were denied. Allow the deploy user's EC2 template to disassociate Elastic IP addresses, so the destroy no longer stops on the NAT address.
- Wait for HAPI FHIR to pass its health check before the setup task loads the cohort, instead of failing on HTTP 502 from a new target.
- Record load-test WebSocket subscriptions that close before the run ends, with their close codes, so missing deliveries show their cause.
- Verify processor write health and actual write denial before replay submission. Remove the run's temporary Deny policy and verify processor writes during cleanup, then remove only owned terminal messages after a bounded quiet interval. The original deployed replay and load failures still require fresh live verification.

### Added

- Add the local warehouse. `python -m jobs.local_warehouse.load` loads the batch into the local Postgres `raw` schema in the Glue job's row format; `python -m jobs.cohort_reference.extract` adds Synthea demographics, payer history, facilities and the batch admissions; `python -m jobs.local_warehouse.dbt` runs the dbt models there through dbt-postgres 1.11.0. Cross-adapter macros keep the Athena SQL unchanged. With `cohort_reference_enabled`, dbt builds `dim_patient_version` (payer SCD2 with demographics), `dim_facility`, `dim_unit` (facility and unit with a care level from the `hospital_units` seed), `fact_admissions` and `fact_encounter_minute_features`. `ml_training_dataset` then splits by waveform split group. `python -m e2e.local_warehouse` checks it end to end. SQLFluff lints both sides of the switch. See Local Stack.
- Each simulator and batch encounter is now a simulated admission: a Synthea facility, a unit, an admitting diagnosis and a 24 to 144 hour stay, seeded by the run. Only inpatient-grade disorders from the simulator's admitting list qualify; a patient with none gets a common medical admission marked `simulator_fallback`. The loader stores each patient's facilities and disorders in the resource map. Batch encounters are completed stays with status `finished` and are updated by identifier. The second encounter starts 14 days after the first.
- Add `COHORT_SIZE` (10 by default, as on AWS; up to 100 for local development) for the loader, the resource-map check and the simulator. Synthea now generates 100 adult patients, aged 18 to 90 (`AGE_RANGE`), with seed `4817263` instead of 12345; The AWS cohort is their first 10. The simulator's blood-pressure file covers all 100. Patients 54 to 100 reuse BIDMC waveform records 1 to 47 from their midpoint, with a seeded per-vital offset and noise so their feature-window vitals differ from the first use.
- Add `python -m jobs.batch_vitals.generate`: two 30-minute encounters per patient, one per scenario, created in HAPI FHIR and written as NDJSON in the stream processor's event format, with a manifest. Records the processor would reject are counted, not written; reruns reuse the encounters and write identical files. `split_groups.json` maps each patient to its waveform record for a record-grouped model split. `python -m e2e.local_cohort` checks the 100-patient cohort and batch end to end.
- Add a local Docker stack (`deploy/local/compose.yaml`) with Postgres 16.15, HAPI FHIR v8.10.0-3 and Grafana 13.2.3 on localhost-only ports. HAPI assigns UUID patient IDs; Grafana reads the warehouse through a read-only role. `scripts/local/local_stack.sh` generates local passwords once and starts, stops or resets the stack; `python -m e2e.local_stack` checks it end to end. See Local Stack.
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
