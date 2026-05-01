# Application Agents

This document outlines the primary actors running in the LzyDownloader Discord Bridge environment.

## 1. The Interaction Agent (Discord Bot)
The primary Python process (`bot.py`) that maintains a connection to the Discord Gateway.

- **Lifecycle:** Runs continuously until `/stop`, `stop_bot.bat`, or process shutdown closes it.
- **Tasks:**
  - Listens for `/download`, `/audio`, `/retry_failed`, `/clear_failed`, `/help`, `/ping`, and `/stop` commands from the authorized Discord user.
  - Accepts authorized direct-message URLs as standard video download requests.
  - Sends online and offline notification DMs to the authorized user when connecting or gracefully shutting down.
  - Checks the health of the local C++ API and launches the Download Worker if it is not running.
  - Reads the local bearer token from `%LOCALAPPDATA%\LzyDownloader\Server\api_token.txt`.
  - Creates asynchronous tasks (`asyncio` loops) to poll the `GET /status` endpoint for progress updates.
  - Formats API responses into ASCII progress bars and updates Discord messages.
  - Tracks active download jobs and sends final notifications when individual downloads and the entire queue complete.
  - Reads `downloads_backup.json` to resume startup work and retry or clear failed/stopped recovery jobs.
  - Archives previous backup files before recovery cleanup so recovery state is not discarded silently.
  - Uses a local single-instance lock so only one bridge process runs at a time.

## 2. The Download Worker Agent (C++ App)
The headless instance of the LzyDownloader Qt6 application.

- **Lifecycle:** Ephemeral. Launched on demand by the Interaction Agent via CLI (`--server --exit-after`); cleanly shuts itself down when the queue is empty.
- **Tasks:**
  - Processes the actual media downloads.
  - Applies the user's shared LzyDownloader GUI preferences from the main application settings.
  - Calculates speeds, ETAs, progress metrics, and job statuses.
  - Exposes these metrics over the local HTTP server (`127.0.0.1:8765`).
  - Persists server-mode queue recovery data in `%LOCALAPPDATA%\LzyDownloader\Server\downloads_backup.json`.
