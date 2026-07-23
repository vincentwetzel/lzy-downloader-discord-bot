# LzyDownloader Discord Bridge v1.2.9

This release strengthens recovery and lifecycle handling for the Discord bridge, improves queue visibility, and keeps the setup and architecture documentation aligned with the current behavior.

## Highlights

- Added reliable fallback paths for installations where `LOCALAPPDATA` is unavailable.
- Prevented offline DM catch-up from re-queueing URLs that are already present in the recovery backup queue.
- Improved recovery cleanup and backup archiving so inactive jobs can be removed without silently discarding recovery state.
- Added real-time queue positions to Discord progress updates.
- Hardened bridge shutdown and cleanup handling to reduce orphaned worker processes and stale state.
- Increased the metadata-fetch timeout window for slower sources.
- Improved completion and failure status reporting in the original Discord progress message.
- Renamed the bridge entrypoint and Windows launchers to project-specific names so they do not collide with other Python bots or scripts.

## Recovery and reliability

- Startup recovery resumes queued work from `downloads_backup.json` and avoids duplicate requests during offline DM scanning.
- Recovery cleanup archives the previous backup before pruning inactive entries.
- Retry and clear commands provide clearer feedback when no eligible recovery jobs exist.
- The bridge continues to enforce single-instance execution and manages the headless Download Worker lifecycle.
- Local API token and backup-file discovery now use the documented `%LOCALAPPDATA%` path with a `%USERPROFILE%\\AppData\\Local` fallback.

## Discord experience

- Progress messages include queue position, percentage, speed, and ETA.
- Download completion messages clearly distinguish successful and failed jobs.
- Dynamic titles and status text are sanitized before being displayed in Discord.
- Authorized direct-message URL downloads and offline catch-up behavior are documented.

## Documentation

- Updated setup instructions, runtime file locations, recovery behavior, command documentation, and architecture notes.
- The repository and runtime now report release version `1.2.9`.

## Upgrade notes

No configuration migration is required. Existing `.env` values and LzyDownloader GUI preferences continue to be used. The bridge may create `.bak` recovery archives during cleanup; these are retained according to the documented archive policy.

## Checks

- Python module compilation check: `python -m py_compile lzy_downloader_discord_bridge.py`
- Version consistency check: `1.2.9` in `README.md` and `lzy_downloader_discord_bridge.py`
