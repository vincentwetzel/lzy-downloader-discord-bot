# Changelog

All notable changes to the Discord bridge are recorded here. The current
release remains `v1.2.9`; the entries below describe the unreleased working
changes documented in this repository.

## Unreleased

### Changed

- **Self-hosting guidance:** Public `/help` and unauthorized slash commands
  or direct messages explain how users can install LzyDownloader and run the
  bridge with their own Discord bot instead of only saying `Unauthorized` or
  staying silent. The authorized owner's online notification remains
  status-only.
- **Headless launch diagnostics:** On Windows, the bridge validates that
  LzyDownloader can load before spawning it, reports missing runtime DLLs in
  Discord, and starts the child with hidden-window flags.
- **Configurable desktop API port:** The bridge now reads the C++ app-local
  `api_port.txt` discovery file and falls back to the stable `8765` default.
- **Shared coordinator support:** The bridge now uses LzyDownloader's shared
  API token and queue backup, accepts a successful secondary `--server` launch
  as an attachment to an existing GUI coordinator, and never terminates that
  coordinator during bridge shutdown. It can still pre-register recovery items
  from a legacy Server backup during the one-time desktop migration.

### Documentation

- Documented explicit `aiohttp` installation, dynamic `.env` reloads before
  worker launch, Unicode progress-bar rendering, and the sensitive contents of
  diagnostic logs.
- Documented coordinator-wide API-token discovery and the read-only legacy
  Server-token fallback used during upgrades.
- Documented that resolved local paths are redacted from Discord-facing
  diagnostics and replaced the executable-path example with a symbolic value.
- Documented Windows-only launcher/supervisor conveniences separately from the
  portable Python entrypoint and platform data-root support.

### Security

- Redacted Windows, POSIX, and local file-URI paths from API errors, worker
  launch failures, webhook terminal diagnostics, and other Discord responses.
- Removed resolved backup and executable paths from routine Discord status
  messages.

### Fixed

- **Pending enqueue handling:** Discord jobs rejected while the shared
  coordinator is already validating another request now receive the terminal
  failure webhook instead of remaining tracked until the timeout.
- Made bridge token, backup, and recovery-archive discovery follow the C++
  application's Windows, Linux, and macOS data directories instead of treating
  the Windows `%USERPROFILE%` template as a literal POSIX path.

### Added

- Added restart-safe Discord status tracking. Active jobs now persist their
  Discord message references, and legacy progress messages can be recovered
  from the most recent 100 DM messages without leaving old partial-progress
  messages frozen. State writes are atomic, and missing or corrupt state does
  not prevent startup.
- Added `/downloads` to list up to 20 active bridge jobs with private job IDs,
  titles, and current statuses.
- Added `/cancel <job_id>` with autocomplete for tracked active jobs.
- Added `cancel <job_id>` and `/cancel <job_id>` support in authorized DMs.
- Added authenticated forwarding to the C++ `POST /cancel` endpoint without
  launching a new worker process.
- Added bridge-generated UUIDs for new enqueue requests, sent as both `job_id`
  and the compatibility `id` field.

### Changed

- Prolonged Discord Gateway disconnections now cause a clean bridge exit after
  a bounded recovery window, allowing the detached supervisor to restart the
  process after sleep/wake failures. The start launcher also avoids creating
  duplicate supervisor loops.
- `/stop` now writes the supervisor shutdown marker before closing, preventing
  the Windows launcher from immediately restarting the bot.
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
- Active Discord progress prefers the C++ `overall_progress` webhook field for
  multi-stream downloads and ignores regressive aggregate updates, preventing
  percentage resets during video/audio handoff or webhook reordering.
- Terminal webhook state is now monotonic: late non-terminal progress updates
  cannot overwrite a completed, failed, stopped, or cancelled Discord message.
- Recovery documentation now specifies the authenticated local API contract,
  webhook terminal states, request payloads, and fallback runtime paths.

### Compatibility and safety

- Legacy server-mode recovery files remain readable through a read-only
  fallback while the C++ coordinator migrates active state to the shared
  queue and token locations.
- Only the authorized Discord user can inspect active jobs or request
  cancellation.
- Dynamic titles, statuses, and backend diagnostics continue to be escaped
  before being rendered in Discord messages.
