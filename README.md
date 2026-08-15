# LzyDownloader Discord Bridge

Current release: `v1.2.9`

A lightweight Python Discord bot that acts as a remote control for **[LzyDownloader](https://github.com/vincentwetzel/lzy-downloader)**, a local C++ Qt6 desktop application.

## Overview
Instead of baking heavy Discord SDKs directly into the C++ desktop app, LzyDownloader exposes a secure local API (`127.0.0.1:8765`). This Python bot listens for Discord slash commands and authorized DMs, communicates with the local C++ API, and provides real-time progress updates directly in Discord.

## Available Commands
*Project Requirement: This list must be kept updated as new commands are added to the bot.*
- `/audio <url>` - Start a new audio-only download.
- `/clear_failed` - Clear inactive recovery jobs (failed, stopped, errored, or completed) from `downloads_backup.json`.
- `/download <url>` - Start a new standard video download.
- `/help` - List all available commands.
- `/ping` - Ping the bot to check its status.
- `/retry_failed` - Retry failed, stopped, or errored recovery jobs from `downloads_backup.json`.
- `/stop` - Gracefully shut down the Discord bot.

Authorized users can also DM the bot a plain HTTP/HTTPS URL to start a standard video download without using a slash command. In DMs, send `ping` to verify that the bot is online.

## Features
- **Slash Commands:** Supports `/download <url>`, `/audio <url>`, `/retry_failed`, `/clear_failed`, `/help`, `/ping`, and `/stop`.
- **Direct Message Downloads:** Send the bot a URL in DMs to enqueue a download from anywhere Discord is available.
- **Offline DM Catch-Up:** On startup, the bot checks recent authorized DM history for URL requests it missed while offline and starts any unacknowledged requests oldest-first, while skipping URLs that are already present in the recovery backup so resumed downloads are not queued twice.
- **Auto-Launching:** If the LzyDownloader app is closed, the bot automatically launches it silently in headless server mode (`--server --exit-after`).
- **Startup Recovery:** If server-mode downloads were saved in `downloads_backup.json`, the bot registers them before relaunching LzyDownloader, prunes completed entries, and resumes progress tracking without losing startup webhook events.
- **Dynamic URL Expansion:** Seamlessly maps internal ID changes from URL expansions (e.g., YouTube Shorts or playlists) back to the original Discord request to keep the UI perfectly synced.
- **Failed Job Recovery:** Failed, stopped, or errored backup entries can be retried without restarting the bot.
- **Inactive Job Cleanup:** Failed, stopped, errored, and completed backup entries can be cleared after archiving the previous backup file.
- **Backup Archiving:** Recovery and clear operations preserve old `downloads_backup.json` files as `.bak` archives and prune older bridge-created archives.
- **Lifecycle Notifications:** Sends a DM to the authorized user when the bot connects to Discord and when it gracefully shuts down.
- **Shared Preferences:** Downloads use the same LzyDownloader preferences configured in the GUI; the bridge does not maintain a separate settings file.
- **Live Progress Bars:** Updates Discord messages with an ASCII progress bar, ETA, download speed, dynamic queue position, and status.
- **Completion Status:** Updates the original Discord progress message with a final completion or failure status when the download finishes.
- **Intentional Re-downloads:** Bot enqueue requests explicitly confirm archive override, so a URL already completed in the shared archive does not wait for the GUI duplicate-download dialog.
- **Message Sanitization:** Safely escapes markdown and spoiler tags from dynamic content (like video titles and status text) to ensure clean formatting in the Discord UI.
- **Secure Communication:** Uses auto-generated local API tokens so only the bot can communicate with the local application.
- **Single-Instance Guard:** Prevents accidentally running multiple bridge processes at the same time.
- **Sleep/Wake Recovery:** The Windows start script supervises the bridge and automatically restarts it if a sleep/wake-related gateway or process failure causes it to exit. The stop script disables this restart loop before shutting it down.
- **Non-Blocking Launcher:** The Windows start script returns immediately after starting its detached supervisor, while the supervisor continues managing the bridge in the background.
- **Auto-Shutdown & Cleanup:** The C++ app automatically closes when the queue is finished. If the bot crashes or is stopped, any lingering headless C++ processes are terminated to prevent orphaned background work.
- **Persistent Diagnostics:** Bridge output, `discord.py`/`aiohttp` diagnostics, and uncaught Python tracebacks are written to `bot.log` beside the bridge script. The active file rotates at 10 MB; archived files are timestamped and five are retained.

## Prerequisites
- Python 3.9+ (Required for `asyncio.to_thread` support)
- [LzyDownloader](https://github.com/vincentwetzel/lzy-downloader) installed on your machine.
- A registered Discord Bot application with a valid token.

## Setting Up The Discord Bot
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** in the top right and give it a name.
3. Navigate to the **Bot** tab on the left sidebar.
4. Click **Reset Token** or **Copy** and save the generated token. This is your `DISCORD_BOT_TOKEN`.
5. To invite the bot to your server, go to **OAuth2 > OAuth2 URL Generator** in the sidebar.
6. Check the `bot` and `applications.commands` scopes.
7. Copy the generated URL, paste it into your browser, and select the server to invite your bot to.

## Installation
1. Clone this repository.
2. Install the required Python packages:
   ```bash
   pip install discord.py python-dotenv requests
   ```
3. Copy `.env.example` to `.env` in the root of the project, then fill in your Discord bot token, authorized user ID, and LzyDownloader executable path:
   ```env
   DISCORD_BOT_TOKEN=your_discord_bot_token_here
   AUTHORIZED_USER_ID=your_user_id_here
   LZY_EXECUTABLE_PATH=C:\Path\To\Your\LzyDownloader.exe
   ```
4. To get your Discord user ID, enable Developer Mode in Discord (`Settings > Advanced > Developer Mode`), then right-click your profile and select **Copy User ID**.
5. In the Discord Developer Portal, enable the **Message Content Intent** for the bot if you want direct-message URL downloads.

## Usage
Run the bot via the command line:
```bash
python lzy_downloader_discord_bridge.py
```

On Windows, you can also use the helper scripts:
```bat
start_lzy_downloader_discord_bridge.bat
stop_lzy_downloader_discord_bridge.bat
```

Once the bot is online, open Discord and run:
```text
/download url:https://www.youtube.com/watch?v=...
/audio url:https://www.youtube.com/watch?v=...
```

The bot starts the download locally on your PC and reports progress in Discord. Use `/retry_failed` to requeue failed, stopped, or errored recovery jobs, and `/clear_failed` to remove inactive backup entries after archiving the previous backup.

## Runtime Files
- API token: `%LOCALAPPDATA%\LzyDownloader\Server\api_token.txt` or, if `LOCALAPPDATA` is unavailable, `%USERPROFILE%\AppData\Local\LzyDownloader\Server\api_token.txt`
- Server-mode backup queue: `%LOCALAPPDATA%\LzyDownloader\Server\downloads_backup.json` or, if `LOCALAPPDATA` is unavailable, `%USERPROFILE%\AppData\Local\LzyDownloader\Server\downloads_backup.json`
- Bridge-created recovery archives: `%LOCALAPPDATA%\LzyDownloader\Server\downloads_backup.json.*.bak` or, if `LOCALAPPDATA` is unavailable, `%USERPROFILE%\AppData\Local\LzyDownloader\Server\downloads_backup.json.*.bak`
- Example environment template: `.env.example`
- Bridge log: `bot.log` beside `lzy_downloader_discord_bridge.py`; rotated archives use names such as `bot_2026-08-12_231530.log` and five are retained

## Architecture
Read [ARCHITECTURE.md](ARCHITECTURE.md) for technical context on the local API schema, auth flow, recovery behavior, and state management. Read [AGENTS.md](AGENTS.md) for the active background actors.

## Development & Contributing
When contributing to the codebase, keep Python code PEP 8 compliant and include type hints for function arguments and return types.
