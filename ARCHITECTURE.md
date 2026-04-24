# LzyDownloader System Architecture

## System Overview
The project is split into two distinct components: the frontend Python Discord Bot and the backend C++ Qt6 Desktop Application. They communicate securely via a local REST API.

### 1. Local API Server (C++ Backend)
- **Endpoint:** `127.0.0.1:8765`
- **Framework:** C++ Qt6
- **Features:** 
  - Exposes `POST /enqueue` to add downloads to the queue.
  - Exposes `GET /status` to retrieve an array of active jobs (progress, speed, ETA, status, title).
- **Background Mode:** Launched with `--background --exit-after`, allowing it to run hidden in the system tray and safely terminate when the download queue completes.

### 2. Discord Bridge Bot (Python Frontend)
- **Framework:** `discord.py`
- **Responsibilities:**
  - Handles the `/download` slash commands.
  - Manages the lifecycle of the C++ app (auto-launching if closed).
  - Polls the local API to provide live progress updates inside Discord messages.

## Security & Authentication
- **Local Bind Only:** The C++ API server only listens on localhost (`127.0.0.1`), preventing external network access.
- **Bearer Token Auth:** On startup, the C++ application generates a 32-character random API key and writes it to `%LOCALAPPDATA%\LzyDownloader\api_token.txt`. The Python bot reads this file and includes the token in the `Authorization: Bearer <token>` header for all local requests.