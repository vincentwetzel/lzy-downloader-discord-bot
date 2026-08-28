# LzyDownloader System Architecture

## System Overview
The project is split into two distinct components: the frontend Python Discord bot and the backend C++ Qt6 desktop application. They communicate securely through a local REST API.

### 1. Local API Server (C++ Backend)
- **Endpoint:** `127.0.0.1:8765`
- **Framework:** C++ Qt6
- **Features:**
  - Exposes `POST /enqueue` to add downloads to the queue, including the requested download type (`video` or `audio`).
  - Exposes authenticated `POST /cancel` with `job_id` to route cancellation through the C++ download manager.
  - Exposes `GET /status` to retrieve active jobs with URL, title, progress, speed, ETA, and status data.
  - Pushes real-time state changes to the Discord bot's webhook server.
  - Persists server-mode queue state in `downloads_backup.json` so interrupted or failed work can be inspected or recovered later.
- **Server Mode:** Launched with `--server --exit-after`, allowing it to run headlessly and terminate when the download queue completes.
- **Settings Ownership:** User preferences remain owned by the C++ app's shared `settings.ini`; the bridge does not create or modify settings files.

### 2. Discord Bridge Bot (Python Frontend)
- **Framework:** `discord.py`
- **Entrypoint:** `lzy_downloader_discord_bridge.py`
- **Windows launchers:** `start_lzy_downloader_discord_bridge.bat` and `stop_lzy_downloader_discord_bridge.bat`
- **Windows supervision:** The start launcher hands the supervisor loop to a minimized detached command child, then returns immediately. The bridge exits after prolonged Discord Gateway loss so the supervisor can restart it after sleep/wake failures. The launcher prevents duplicate supervisor loops, and the stop launcher writes a marker to prevent an intentional shutdown from being restarted.
- **Responsibilities:**
  - Handles `/download`, `/audio`, `/downloads`, `/cancel`, `/retry_failed`, `/clear_failed`, `/help`, `/ping`, and `/stop` slash commands.
  - Accepts authorized direct-message URLs as standard video downloads.
  - Scans recent authorized DM history on startup for unacknowledged URL requests sent while the bot was offline.
  - Notifies the authorized user via DM when it successfully connects to Discord or gracefully shuts down.
  - Manages the lifecycle of the C++ app, including auto-launching it when the local API is unavailable and forcefully terminating it when the bridge shuts down.
  - Hosts a local webhook server (`127.0.0.1:8766`) to receive instant, event-driven progress updates from the C++ app.
  - **Strictly Event-Driven:** Polling the local API (e.g., `GET /status`) for live progress updates is explicitly forbidden. All state tracking must rely solely on the push updates provided by the webhook server.
  - Tracks active download jobs so the user receives completion and queue-empty notifications.
  - Prevents duplicate bot processes by binding a local single-instance lock socket.
  - Sanitizes dynamic data (video titles, API errors, status texts) from the C++ API to prevent unintended Discord markdown or spoiler formatting.
  - Writes bridge output, Discord/aiohttp library diagnostics, incoming webhook payloads, and uncaught exception tracebacks to `bot.log` beside the entrypoint. The active file rotates at 10 MB into timestamped archives, retaining five. Because webhook payloads can contain URLs, titles, or backend errors, the log file must be treated as local-sensitive data.

## Security & Authentication
- **Local Bind Only:** The C++ API server only listens on localhost (`127.0.0.1`), preventing external network access.
- **Bearer Token Auth:** The C++ application generates a random API key and writes it to an AppData token file. The Python bot checks the server token path (`%LOCALAPPDATA%\LzyDownloader\Server\api_token.txt`) first, then the GUI token path (`%LOCALAPPDATA%\LzyDownloader\api_token.txt`), validates candidates against the local API, and includes the working token in the `Authorization: Bearer <token>` header. If `LOCALAPPDATA` is missing, both paths use the `%USERPROFILE%\AppData\Local` fallback.
- **User Authorization:** The bridge requires `AUTHORIZED_USER_ID` and rejects commands or DMs from any other Discord user.
- **Local Single Instance:** The bridge binds a local UDP socket on `127.0.0.1:48765` to prevent multiple bot processes from issuing competing requests.
- **Environment Template:** `.env.example` documents the required bridge variables (`DISCORD_BOT_TOKEN`, `AUTHORIZED_USER_ID`, and `LZY_EXECUTABLE_PATH`) for local setup.

## Download Flow
1. An authorized user sends `/download`, `/audio`, or a URL in DM. Active job IDs can be listed with `/downloads` and cancelled with `/cancel`; DMs also accept `cancel <job_id>`.
2. The bot validates the URL and checks whether the local API is already healthy.
3. If needed, the bot launches LzyDownloader with `--server --exit-after`.
4. The bot reads the local API token and sends `POST /enqueue` with the URL, download type, and an explicit `override_archive` confirmation for intentional bot requests.
   - Cancellation uses the same bearer token and sends `POST /cancel` with `job_id`; the bridge waits for the C++ `Cancelled` webhook state before closing its progress task.
   - New jobs use a bridge-generated UUID in both `job_id` and `id` before `/enqueue` is sent. If the backend rejects the URL asynchronously, the rejection webhook can therefore update and clean up the correct Discord job.
5. The bot receives instant webhook POST requests on `127.0.0.1:8766` and smoothly edits the original Discord message with progress, including the job's active queue position. (Polling is strictly prohibited).
   - *Note on URL Expansion:* If LzyDownloader expands a URL or playlist (which spawns a child item with a new internal ID), the bot dynamically routes the incoming webhook payloads back to the original tracked job using `parent_id` or fuzzy URL matching.
6. When the job completes or leaves the active queue, the bot updates the original message with a final completion or failure status. Backend error text is included when available, then the job is removed from `active_jobs`.
   - Non-interactive validation failures use the caller-supplied job ID, include the generic backend diagnostic, update the Discord message, and are removed from `active_jobs` through the normal terminal cleanup path.

## Offline DM Catch-Up
- After Discord reports the bridge as ready, the bot sends the authorized user an online DM and reads the most recent DM messages.
- Authorized HTTP/HTTPS URL messages are treated as missed requests when no newer bot reply in the scanned history references the same URL and the URL is not already present in the recovery backup queue.
- Missed requests are acknowledged in Discord and queued oldest-first using the same standard video download path as live DM URL requests.
- The scan is intentionally limited to recent DM history so startup remains bounded and previously acknowledged requests are not replayed indefinitely.
- This duplicate-prevention step keeps startup catch-up from re-queuing downloads that are already scheduled for recovery from `downloads_backup.json`.

## Recovery Flow
- The bridge reads `%LOCALAPPDATA%\LzyDownloader\Server\downloads_backup.json` for server-mode backup entries.
- Queued resumable entries can be resumed after startup by relaunching LzyDownloader and reattaching Discord progress tracking.
- Recovery tracking entries are registered before the first LzyDownloader launch because server startup immediately emits events for every restored queue item. `on_ready()` completes this setup before missed-DM catch-up can start another task.
- Failed, stopped, or errored entries are treated as stranded jobs and are not assumed to auto-run safely.
- Completed entries are pruned from the backup file during startup recovery so they do not linger as resumable work.
- `/retry_failed` archives the previous backup, preserves still-queued resumable entries, and re-enqueues failed, stopped, or errored URLs for fresh tracking.
- Before `/retry_failed` enqueues work, the bridge keeps one record per generic normalized URL identity and download type. The same identity is used when comparing offline DM requests with backup entries, so tracking/share query changes cannot create a second recovery job.
- `/clear_failed` archives the previous backup and rewrites the backup file with only resumable queued entries, removing failed, stopped, errored, and completed entries.
- Bridge-created archive files use names like `downloads_backup.json.discord_recovery_<timestamp>.bak` and `downloads_backup.json.cleared_failed_<timestamp>.bak`.

## Local API Contract

- The C++ API listens on `127.0.0.1:8765`; the bridge webhook listener accepts `POST /webhook` on `127.0.0.1:8766`.
- API requests use a bearer token discovered from the server or GUI `api_token.txt` path and validated against the local API. Enqueue requests include `url`, `download_type`, `override_archive: true`, and a caller-supplied `job_id`/`id`.
- Cancellation sends `POST /cancel` with `{ "job_id": "..." }`. Cancellation is only sent for a job currently tracked by the bridge; the terminal result arrives through the webhook.
- Webhook payloads may identify a job with `job_id`, `id`, `jobId`, or `lzy_id`, and may include `parent_id`, `url`, `status`, `title`, progress fields, and `error`.
- Multi-stream webhook payloads may include `overall_progress` as a finite percentage from 0 through 100; the bridge uses that field for active Discord rendering because the ordinary `progress` field is scoped to the currently transferring stream and can reset at video/audio handoff. Regressive aggregate updates are ignored while the job remains active, while terminal updates may set the final raw progress value.
- The bridge registers a UUID locally before sending `/enqueue`. If the API returns a different ID, the temporary registration is replaced with the server ID; if the API rejects the request before returning a response, the caller ID remains available for matching the terminal webhook.
- The bridge treats `completed`, `complete`, `finished`, `failed`, `stopped`, `error`, `cancelled`, and `canceled` as terminal statuses. A webhook `error` value is retained and included in the final Discord diagnostic after markdown escaping and length limiting.

### Request examples

```http
POST /enqueue
Authorization: Bearer <api-token>
Content-Type: application/json

{"url":"https://example.test/media","download_type":"video","override_archive":true,"job_id":"<uuid>","id":"<uuid>"}
```

```http
POST /cancel
Authorization: Bearer <api-token>
Content-Type: application/json

{"job_id":"<tracked-job-id>"}
```

The bridge does not poll `GET /status` for progress. `/status` may be used by
the local application for diagnostics, but Discord progress and terminal state
are driven exclusively by webhook events.

When the API is unavailable and a worker launch is required, the bridge reloads
`.env` immediately before reading `LZY_EXECUTABLE_PATH`. This permits a changed
executable path to be picked up by the next launch attempt without restarting
the bridge process.

## Runtime Files
- `.env` in the bridge directory stores `DISCORD_BOT_TOKEN`, `AUTHORIZED_USER_ID`, and `LZY_EXECUTABLE_PATH`.
- `%LOCALAPPDATA%\LzyDownloader\Server\api_token.txt` is the preferred local API bearer-token path; `%LOCALAPPDATA%\LzyDownloader\api_token.txt` is also checked for GUI-managed tokens. When `LOCALAPPDATA` is unavailable, the corresponding fallback paths are under `%USERPROFILE%\AppData\Local\LzyDownloader`.
- `%LOCALAPPDATA%\LzyDownloader\Server\downloads_backup.json` stores LzyDownloader server-mode recovery state, with `%USERPROFILE%\AppData\Local\LzyDownloader\Server\downloads_backup.json` as the fallback path when `LOCALAPPDATA` is unavailable.
- `%LOCALAPPDATA%\LzyDownloader\Server\downloads_backup.json.*.bak` stores bridge-created backup archives, with `%USERPROFILE%\AppData\Local\LzyDownloader\Server\downloads_backup.json.*.bak` as the fallback path when `LOCALAPPDATA` is unavailable.
- `bot.log` beside `lzy_downloader_discord_bridge.py` stores active diagnostics, including incoming webhook payloads; rotated files use timestamped names such as `bot_2026-08-12_231530.log`. Restrict access because entries may contain requested URLs, titles, and backend errors.
