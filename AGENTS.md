# Application Agents

This document outlines the primary actors running in the LzyDownloader Discord Bridge environment.

## 1. The Interaction Agent (Discord Bot)
The primary Python process (`lzy_downloader_discord_bridge.py`) that maintains a connection to the Discord Gateway.

- **Lifecycle:** Runs continuously until `/stop`, `stop_lzy_downloader_discord_bridge.bat`, or process shutdown closes it. `/stop` and the stop batch file write the supervisor shutdown marker before intentional exit. A prolonged Discord Gateway outage causes a clean exit for the detached supervisor to restart; the start batch file prevents duplicate supervisor loops.
- **Tasks:**
  - Listens for `/download`, `/audio`, `/downloads`, `/cancel`, `/retry_failed`, `/clear_failed`, `/help`, `/ping`, and `/stop` commands from the authorized Discord user.
  - Accepts authorized direct-message URLs as standard video download requests.
  - Scans recent authorized direct messages on startup and queues unacknowledged offline URL requests oldest-first, while skipping URLs already present in the recovery backup queue to avoid duplicate re-queueing.
  - Sends online and offline notification DMs to the authorized user when connecting or gracefully shutting down.
  - Checks the health of the local C++ API, launches the Download Worker if it is not running, and ensures it is properly terminated when the bridge shuts down.
  - Reads and validates the local bearer token from the server token path, then the GUI token path, under the platform data root: `%LOCALAPPDATA%` on Windows, XDG data or `~/.local/share` on Linux, and `~/Library/Application Support` on macOS.
  - Hosts an asynchronous webhook listener (`aiohttp`) to receive push updates from the C++ app.
  - Formats webhook JSON payloads into compact Unicode progress bars, displays real-time queue positions, and updates Discord messages with a debounce mechanism.
  - Uses the C++ `overall_progress` webhook field for multi-stream jobs so Discord percentages remain monotonic across video/audio stream handoff.
  - Treats terminal webhook state as monotonic, ignoring late non-terminal progress events that were posted before completion but arrive afterward.
  - Tracks active download jobs and updates the original message with a final status when individual downloads complete.
  - Sends authenticated cancellation requests for active job IDs and recognizes `Cancelled`/`Canceled` webhook states as terminal.
  - Generates and registers a UUID before each new enqueue request, passing it as both `job_id` and `id` so asynchronous backend validation failures remain associated with the originating Discord message.
  - Pre-registers caller-supplied job IDs before enqueueing so asynchronous validation failures can be matched, reported, and removed immediately.
  - Pre-registers all queued recovery jobs before launching the C++ worker so startup webhook events cannot arrive before bridge tracking exists.
  - Sanitizes dynamic webhook text (like titles and status updates) to prevent accidental Discord markdown rendering, and redacts Windows, POSIX, and local file-URI paths before diagnostic text is sent to Discord.
  - Reads `downloads_backup.json` from the platform data root under `LzyDownloader/Server` to resume startup work, prune completed backup entries, and retry or clear inactive recovery jobs.
  - Uses extractor-independent URL identity normalization to avoid re-queueing equivalent recovery entries or offline DM requests that differ only by tracking/share parameters.
  - Includes backend `error` diagnostics in terminal Discord messages when supplied by a webhook.
  - Archives previous backup files before recovery cleanup so recovery state is not discarded silently.
  - Uses a local single-instance lock so only one bridge process runs at a time.
  - Reloads `.env` immediately before launching the worker, allowing an updated `LZY_EXECUTABLE_PATH` to be used without restarting the bridge.
  - Writes bridge, library, exception, and incoming webhook diagnostics to `bot.log`; log files may contain URLs, titles, backend errors, and local diagnostic details and must be treated as sensitive local data. Resolved local paths must not be included in Discord-facing messages.

## 2. The Download Worker Agent (C++ App)
The headless instance of the LzyDownloader Qt6 application.

- **Lifecycle:** Ephemeral. Launched on demand by the Interaction Agent via CLI (`--server --exit-after`); cleanly shuts itself down when the queue is empty, and is forcefully terminated if the Interaction Agent crashes or stops.
- **Tasks:**
  - Processes the actual media downloads.
  - Applies the user's shared LzyDownloader GUI preferences from the main application settings.
  - Calculates speeds, ETAs, progress metrics, and job statuses.
  - Exposes these metrics over the local HTTP server (`127.0.0.1:8765`).
  - Pushes live state changes to the Interaction Agent via an HTTP `POST` webhook (`127.0.0.1:8766/webhook`).
  - Includes `parent_id` and `url` alongside the `job_id` in its webhook payloads, allowing the bridge to map expanded child jobs back to the original Discord requests.
  - Persists server-mode queue recovery data under the platform data root in `LzyDownloader/Server/downloads_backup.json`, matching the bridge's Windows, Linux, and macOS token/backup locations.

## 3. Development Requirements

Windows, Linux, and macOS are first-class supported platforms for the bridge.
Every path, process, launcher, and documentation change must preserve all
three platforms; Windows-only behavior must have an explicit platform guard
and an equivalent POSIX implementation or documented prerequisite.
The Python entrypoint is the portable runtime boundary; the checked-in batch
launchers and PowerShell supervisor are Windows-only conveniences, so POSIX
deployments must run the entrypoint under an equivalent supervisor.

All code modifying or interacting with these agents must strictly adhere to the guidelines established in CODING_STANDARDS.md.

Documentation must remain synchronized across this file, `README.md`,
`ARCHITECTURE.md`, and `CHANGELOG.md` whenever command behavior, lifecycle,
local API usage, recovery behavior, or runtime files change.
