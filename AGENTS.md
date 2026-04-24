# Application Agents

This document outlines the primary actors or "agents" running in the LzyDownloader Discord Bridge environment.

## 1. The Interaction Agent (Discord Bot)
The primary Python process (`bot.py`) that maintains a connection to the Discord Gateway.
- **Lifecycle:** Runs continuously.
- **Tasks:**
  - Listens for `/download` commands from authorized Discord users.
  - Checks the health of the local C++ API.
  - Spawns the Download Worker if it isn't running.
  - Creates asynchronous tasks (`asyncio` loops) to poll the `GET /status` endpoint every 4 seconds.
  - Formats API responses into ASCII progress bars (`[████░░░░] 50%`) and updates Discord messages.

## 2. The Download Worker Agent (C++ App)
The headless instance of the LzyDownloader Qt6 application.
- **Lifecycle:** Ephemeral. Launched on-demand by the Interaction Agent; shuts itself down (`--exit-after`) when the queue is empty.
- **Tasks:**
  - Processes the actual media downloads.
  - Calculates speeds, ETAs, and progress metrics.
  - Exposes these metrics over the local HTTP server (`127.0.0.1:8765`).