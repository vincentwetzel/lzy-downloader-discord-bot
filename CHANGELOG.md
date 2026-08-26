# Changelog

All notable changes to the Discord bridge are recorded here. The current
release remains `v1.2.9`; the entries below describe the unreleased working
changes documented in this repository.

## Unreleased

### Added

- Added `/downloads` to list up to 20 active bridge jobs with private job IDs,
  titles, and current statuses.
- Added `/cancel <job_id>` with autocomplete for tracked active jobs.
- Added `cancel <job_id>` and `/cancel <job_id>` support in authorized DMs.
- Added authenticated forwarding to the C++ `POST /cancel` endpoint without
  launching a new worker process.
- Added bridge-generated UUIDs for new enqueue requests, sent as both `job_id`
  and the compatibility `id` field.

### Changed

- Cancellation now remains pending until a terminal `Cancelled`/`Canceled`
  webhook event is received.
- Terminal webhook handling now recognizes cancellation states and preserves
  backend `error` diagnostics for the final Discord message.
- Validation failures that arrive asynchronously can now be matched to and
  removed from the originating Discord job because tracking is registered
  before enqueue.
- Recovery and offline-DM duplicate checks now use generic URL identity
  normalization rather than raw URL equality. Tracking and campaign query
  parameters are ignored while content-selection parameters are retained.
- `/retry_failed` deduplicates recovery entries by normalized URL identity and
  download type before submitting new jobs.
- Recovery documentation now specifies the authenticated local API contract,
  webhook terminal states, request payloads, and fallback runtime paths.

### Compatibility and safety

- Existing server-mode recovery files and the shared C++ API token location
  remain unchanged.
- Only the authorized Discord user can inspect active jobs or request
  cancellation.
- Dynamic titles, statuses, and backend diagnostics continue to be escaped
  before being rendered in Discord messages.

