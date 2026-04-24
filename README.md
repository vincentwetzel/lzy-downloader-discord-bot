# LzyDownloader Discord Bridge

A lightweight Python Discord bot that acts as a remote control for **[LzyDownloader](https://github.com/vincentwetzel/lzy-downloader)**, a local C++ Qt6 desktop application.

## Overview
Instead of baking heavy Discord SDKs directly into the C++ desktop app, LzyDownloader exposes a secure local API (`127.0.0.1:8765`). This Python bot listens for Discord slash commands, communicates with the local C++ API, and provides real-time progress updates directly in your Discord chat.

## Features
- **Slash Commands:** Seamless integration with Discord using `/download <url>`.
- **Auto-Launching:** If the LzyDownloader app is closed, the bot automatically launches it silently in the background.
- **Live Progress Bars:** Updates the Discord message in real-time with an ASCII progress bar, ETA, and download speed.
- **Secure Communication:** Uses auto-generated, randomized local API tokens to ensure that only the bot can communicate with the local application.
- **Auto-Shutdown:** The C++ app automatically closes when the queue is finished, freeing up system resources.

## Prerequisites
- Python 3.8+
- [LzyDownloader](https://github.com/vincentwetzel/lzy-downloader) installed on your machine.
- A registered Discord Bot application with a valid token.

## Setting up the Discord Bot
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** in the top right and give it a name.
3. Navigate to the **Bot** tab on the left sidebar.
4. Click **Reset Token** (or **Copy**) and save the generated token. This will be your `DISCORD_BOT_TOKEN`.
5. To invite the bot to your server, go to **OAuth2 > OAuth2 URL Generator** in the sidebar.
6. Check the `bot` and `applications.commands` scopes.
7. Copy the generated URL at the bottom, paste it into your browser, and select the server to invite your bot to.

## Installation

1. Clone this repository.
2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the root of the project and add your Discord bot token and user ID. This secures the bot so only you can use it.
   - To get your User ID, enable Developer Mode in Discord (`Settings > Advanced > Developer Mode`), then right-click your profile and select "Copy User ID".
   ```env
   DISCORD_BOT_TOKEN=your_discord_bot_token_here
   AUTHORIZED_USER_ID=your_user_id_here
   ```
4. Open `bot.py` and ensure the `LZY_EXECUTABLE_PATH` matches the location of your compiled `LzyDownloader.exe`:
   ```python
   LZY_EXECUTABLE_PATH = r"C:\Path\To\Your\LzyDownloader.exe"
   ```

## Usage
Run the bot via the command line:
```bash
python bot.py
```
Once the bot is online, open your Discord server and type:
```
/download url:https://www.youtube.com/watch?v=...
```
The bot will start the download locally on your PC and report the progress!

## Architecture
Read ARCHITECTURE.md for technical context on the local API schema, auth flow, and state management, and AGENTS.md for information on the active background workers.