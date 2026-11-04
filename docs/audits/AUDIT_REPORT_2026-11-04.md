# README documentation audit

Audited against commit `351caa5` and the working tree on 2026-11-04.

## Summary

Reviewed `README.md` against the application, tests, installer, dependency lists, and Snap configuration. Corrected outdated claims and documented missing features; live services and packaging builds were not verified.

## Findings

| Area | Finding |
| --- | --- |
| Installation and launch | Clone URL was a placeholder; dependencies, backend selection, and platform guarantees did not match the implementation. |
| Snap and standalone packaging | The Snap terminal command conflicted with the launcher; settings, asset collection, and installation path claims were too strong. |
| Search and browsing | Search did not describe locally cached catalogs, asynchronous fallbacks, or conditional pagination. |
| Downloads | Concurrency, overwrite confirmation, deduplication, atomicity, and completion-dialog claims overstated safeguards. |
| Data and media | The documented universal fallback cascade, cache details, format priorities, and URL validation did not match the separate code paths. |
| UI and configuration | Hover availability, GTK handling, password fields, destination defaults, and environment aliases needed correction; audio-only mode and cancellation were missing. |

## Pattern review

Checked related command examples, defaults, feature descriptions, and packaging claims for similar drift. External Snap Store availability, confinement behavior, and live TWiT services require separate runtime verification.