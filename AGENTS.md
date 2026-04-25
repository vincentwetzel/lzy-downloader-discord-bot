# Application Agents

This document outlines the primary actors or "agents" running in the LzyDownloader Discord Bridge environment.

## 1. The Interaction Agent (Discord Bot)
The primary Python process (`bot.py`) that maintains a connection to the Discord Gateway.
- **Lifecycle:** Runs continuously.
- **Tasks:**
  - Listens for `/download`, `/audio`, `/help`, `/ping`, and `/stop` commands from authorized Discord users.
  - Accepts authorized direct-message URLs as standard download requests.
  - Checks the health of the local C++ API and launches the Download Worker if it's not running.
  - Creates asynchronous tasks (`asyncio` loops) to poll the `GET /status` endpoint every 4 seconds.
  - Formats API responses into ASCII progress bars (`[#####----------] 50%`) and updates Discord messages.
  - Uses a local single-instance lock so only one bridge process runs at a time.

## 2. The Download Worker Agent (C++ App)
The headless instance of the LzyDownloader Qt6 application.
- **Lifecycle:** Ephemeral. Launched on-demand by the Interaction Agent via CLI (`--server --exit-after`); cleanly shuts itself down when the queue is empty.
- **Tasks:**
  - Processes the actual media downloads.
  - Calculates speeds, ETAs, and progress metrics.
  - Exposes these metrics over the local HTTP server (`127.0.0.1:8765`).
