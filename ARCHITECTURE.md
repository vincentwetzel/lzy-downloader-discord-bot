# LzyDownloader System Architecture

## System Overview
The project is split into two distinct components: the frontend Python Discord bot and the backend C++ Qt6 desktop application. They communicate securely through a local REST API.

### 1. Local API Server (C++ Backend)
- **Endpoint:** `127.0.0.1:8765`
- **Framework:** C++ Qt6
- **Features:**
  - Exposes `POST /enqueue` to add downloads to the queue, including the requested download type (`video` or `audio`).
  - Exposes `GET /status` to retrieve active jobs with URL, title, progress, speed, ETA, and status data.
  - Pushes real-time state changes to the Discord bot's webhook server.
  - Persists server-mode queue state in `downloads_backup.json` so interrupted or failed work can be inspected or recovered later.
- **Server Mode:** Launched with `--server --exit-after`, allowing it to run headlessly and terminate when the download queue completes.
- **Settings Ownership:** User preferences remain owned by the C++ app's shared `settings.ini`; the bridge does not create or modify settings files.

### 2. Discord Bridge Bot (Python Frontend)
- **Framework:** `discord.py`
- **Responsibilities:**
  - Handles `/download`, `/audio`, `/retry_failed`, `/clear_failed`, `/help`, `/ping`, and `/stop` slash commands.
  - Accepts authorized direct-message URLs as standard video downloads.
  - Scans recent authorized DM history on startup for unacknowledged URL requests sent while the bot was offline.
  - Notifies the authorized user via DM when it successfully connects to Discord or gracefully shuts down.
  - Manages the lifecycle of the C++ app, including auto-launching it when the local API is unavailable.
  - Hosts a local webhook server (`127.0.0.1:8766`) to receive instant, event-driven progress updates from the C++ app.
  - Tracks active download jobs so the user receives completion and queue-empty notifications.
  - Prevents duplicate bot processes by binding a local single-instance lock socket.

## Security & Authentication
- **Local Bind Only:** The C++ API server only listens on localhost (`127.0.0.1`), preventing external network access.
- **Bearer Token Auth:** On startup, the C++ application generates a random API key and writes it to `%LOCALAPPDATA%\LzyDownloader\Server\api_token.txt`. The Python bot reads this file and includes the token in the `Authorization: Bearer <token>` header for local API requests.
- **User Authorization:** The bridge requires `AUTHORIZED_USER_ID` and rejects commands or DMs from any other Discord user.
- **Local Single Instance:** The bridge binds a local UDP socket on `127.0.0.1:48765` to prevent multiple bot processes from issuing competing requests.

## Download Flow
1. An authorized user sends `/download`, `/audio`, or a URL in DM.
2. The bot validates the URL and checks whether the local API is already healthy.
3. If needed, the bot launches LzyDownloader with `--server --exit-after`.
4. The bot reads the local API token and sends `POST /enqueue` with the URL and download type.
5. The bot receives instant webhook POST requests on `127.0.0.1:8766` and smoothly edits the original Discord message with progress.
6. When the job completes or leaves the active queue, the bot updates the original message with a final completion or failure status.

## Offline DM Catch-Up
- After Discord reports the bridge as ready, the bot sends the authorized user an online DM and reads the most recent DM messages.
- Authorized HTTP/HTTPS URL messages are treated as missed requests when no newer bot reply in the scanned history references the same URL.
- Missed requests are acknowledged in Discord and queued oldest-first using the same standard video download path as live DM URL requests.
- The scan is intentionally limited to recent DM history so startup remains bounded and previously acknowledged requests are not replayed indefinitely.

## Recovery Flow
- The bridge reads `%LOCALAPPDATA%\LzyDownloader\Server\downloads_backup.json` for server-mode backup entries.
- Queued resumable entries can be resumed after startup by relaunching LzyDownloader and reattaching Discord progress tracking.
- Failed or stopped entries are treated as stranded jobs and are not assumed to auto-run safely.
- `/retry_failed` archives the previous backup, preserves still-queued resumable entries, and re-enqueues failed or stopped URLs for fresh tracking.
- `/clear_failed` archives the previous backup and rewrites the backup file with only resumable queued entries.
- Bridge-created archive files use names like `downloads_backup.json.discord_recovery_<timestamp>.bak` and `downloads_backup.json.cleared_failed_<timestamp>.bak`.

## Runtime Files
- `.env` in the bridge directory stores `DISCORD_BOT_TOKEN`, `AUTHORIZED_USER_ID`, and `LZY_EXECUTABLE_PATH`.
- `%LOCALAPPDATA%\LzyDownloader\Server\api_token.txt` stores the current local API bearer token.
- `%LOCALAPPDATA%\LzyDownloader\Server\downloads_backup.json` stores LzyDownloader server-mode recovery state.
- `%LOCALAPPDATA%\LzyDownloader\Server\downloads_backup.json.*.bak` stores bridge-created backup archives.
