# LzyDownloader Discord Bridge

A lightweight Python Discord bot that acts as a remote control for **[LzyDownloader](https://github.com/vincentwetzel/lzy-downloader)**, a local C++ Qt6 desktop application.

## Overview
Instead of baking heavy Discord SDKs directly into the C++ desktop app, LzyDownloader exposes a secure local API (`127.0.0.1:8765`). This Python bot listens for Discord slash commands and authorized DMs, communicates with the local C++ API, and provides real-time progress updates directly in Discord.

## Available Commands
*Project Requirement: This list must be kept updated as new commands are added to the bot.*
- `/audio <url>` - Start a new audio-only download.
- `/clear_failed` - Clear failed or stopped recovery jobs from `downloads_backup.json`.
- `/download <url>` - Start a new standard video download.
- `/help` - List all available commands.
- `/ping` - Ping the bot to check its status.
- `/retry_failed` - Retry failed or stopped recovery jobs from `downloads_backup.json`.
- `/stop` - Gracefully shut down the Discord bot.

Authorized users can also DM the bot a plain HTTP/HTTPS URL to start a standard video download without using a slash command. In DMs, send `ping` to verify that the bot is online.

## Features
- **Slash Commands:** Supports `/download <url>`, `/audio <url>`, `/retry_failed`, `/clear_failed`, `/help`, `/ping`, and `/stop`.
- **Direct Message Downloads:** Send the bot a URL in DMs to enqueue a download from anywhere Discord is available.
- **Offline DM Catch-Up:** On startup, the bot checks recent authorized DM history for URL requests it missed while offline and starts any unacknowledged requests oldest-first.
- **Auto-Launching:** If the LzyDownloader app is closed, the bot automatically launches it silently in headless server mode (`--server --exit-after`).
- **Startup Recovery:** If server-mode downloads were saved in `downloads_backup.json`, the bot can relaunch LzyDownloader and resume progress tracking on startup.
- **Failed Job Recovery:** Failed or stopped backup entries can be retried without restarting the bot, or cleared after archiving the previous backup file.
- **Backup Archiving:** Recovery and clear operations preserve old `downloads_backup.json` files as `.bak` archives and prune older bridge-created archives.
- **Lifecycle Notifications:** Sends a DM to the authorized user when the bot connects to Discord and when it gracefully shuts down.
- **Shared Preferences:** Downloads use the same LzyDownloader preferences configured in the GUI; the bridge does not maintain a separate settings file.
- **Live Progress Bars:** Updates Discord messages with an ASCII progress bar, ETA, download speed, and status.
- **Duplicate Prevention:** Checks active and backed-up jobs before enqueuing so the same URL/type is not started twice.
- **Completion Notifications:** Sends a final message when an individual download finishes, including a mention when the request came from a server channel.
- **Queue Completion Notification:** After the last tracked item finishes, the bot sends a final confirmation that the queue is complete.
- **Secure Communication:** Uses auto-generated local API tokens so only the bot can communicate with the local application.
- **Single-Instance Guard:** Prevents accidentally running multiple bridge processes at the same time.
- **Auto-Shutdown:** The C++ app automatically closes when the queue is finished, freeing up system resources.

## Prerequisites
- Python 3.8+
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
3. Create a `.env` file in the root of the project and add your Discord bot token, authorized user ID, and LzyDownloader executable path:
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
python bot.py
```

On Windows, you can also use the helper scripts:
```bat
start_bot.bat
stop_bot.bat
```

Once the bot is online, open Discord and run:
```text
/download url:https://www.youtube.com/watch?v=...
/audio url:https://www.youtube.com/watch?v=...
```

The bot starts the download locally on your PC and reports progress in Discord. Use `/retry_failed` to requeue failed or stopped recovery jobs, and `/clear_failed` to remove those failed/stopped backup entries after archiving the previous backup.

## Runtime Files
- API token: `%LOCALAPPDATA%\LzyDownloader\Server\api_token.txt`
- Server-mode backup queue: `%LOCALAPPDATA%\LzyDownloader\Server\downloads_backup.json`
- Bridge-created recovery archives: `%LOCALAPPDATA%\LzyDownloader\Server\downloads_backup.json.*.bak`

## Architecture
Read [ARCHITECTURE.md](ARCHITECTURE.md) for technical context on the local API schema, auth flow, recovery behavior, and state management. Read [AGENTS.md](AGENTS.md) for the active background actors.

## Development & Contributing
When contributing to the codebase, keep Python code PEP 8 compliant and include type hints for function arguments and return types.
