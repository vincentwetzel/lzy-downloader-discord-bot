# LzyDownloader Discord Bot - Coding Standards

Welcome to the coding standards guide for the LzyDownloader Discord Bot project. To maintain a clean, readable, and highly maintainable codebase, all contributors are expected to follow these guidelines.

## 1. General Principles

* **Readability Counts**: Code is read much more often than it is written. Prioritize clarity and intent over "clever" one-liners.
* **DRY (Don't Repeat Yourself)**: Extract reusable logic into dedicated functions or modules.
* **Leave It Better Than You Found It**: When editing a file, try to clean up nearby minor tech debt or formatting inconsistencies.
* **Respect the Architecture**: Always refer to `ARCHITECTURE.md` and `AGENTS.md` before making structural changes. For example, the bridge is strictly event-driven (polling the API for progress is forbidden).
* **Keep Documentation in Sync**: Code changes that alter system behavior, API endpoints, active actors, or runtime files must be accompanied by corresponding updates to `README.md`, `ARCHITECTURE.md`, `AGENTS.md`, and `CHANGELOG.md`. Documentation must describe observed behavior accurately, including limitations such as webhook data being written to local diagnostics.
* **Error Handling**: Always strive to catch specific exceptions (e.g., `requests.exceptions.ConnectionError`) rather than a broad `catch-all` / `except Exception`. If a broad catch is absolutely necessary to prevent a crash (e.g., top-level event handlers), always log the error output so bugs aren't swallowed silently.
* **Path Privacy**: Never send resolved local filesystem paths, executable locations, usernames, or other machine-identifying details to Discord. Redact Windows, POSIX, and local file-URI paths from backend responses and exception text at the Discord message boundary; use relative filenames or generic descriptions instead.
* **HTTP Request Validation**: When making network requests (e.g., via `requests`), always validate the response (e.g., checking `res.status_code == 200` or handling specific API error codes) before attempting to parse JSON payloads. This prevents obscure `JSONDecodeError`s.
* **Resource Management**: Whether in Python or C++, always ensure that child processes, file handles, and network sockets are gracefully closed or terminated during application shutdown to prevent orphaned resources.
* **Atomic File Operations**: When modifying critical state files (like `downloads_backup.json`), prefer atomic writes. Write data to a temporary file first, then seamlessly replace the target file (e.g., using `os.replace()` in Python or `QSaveFile` in C++). This prevents zero-byte file corruption if the application or system crashes mid-write.
* **Logging & Output**: Avoid raw `print()` statements in production code. Prefer Python's built-in `logging` module with standardized level configurations. Use clear prefixes or emojis in log messages (e.g., `[Webhook ERROR]`, `❌`, `🛑`) to allow quick log scanning and support integration with external monitoring systems.
* **Logging Levels**: When using structured logging, use `ERROR` for unexpected failures that require developer attention, `WARNING` for recoverable issues or retries, `INFO` for major lifecycle events (startup, shutdown, job completion), and `DEBUG` for verbose data (like raw webhook payloads).
* **API Data Formats**: When modifying the local API or webhook payloads, standardize on `snake_case` for JSON keys (e.g., prefer `job_id` over `jobId`) to maintain consistency across the Python and C++ boundary.
* **Cancellation Flow**: Remote cancellation must call the authenticated `POST /cancel` endpoint with `job_id`; do not launch a new downloader process merely to cancel a tracked job, and wait for the terminal webhook state.
* **API Backward Compatibility**: This system is not meant to support backward compatibility. Because the Python bot and C++ backend are tightly coupled, developers are free to make breaking changes to the local REST API or webhook payloads, provided that both components are updated synchronously to prevent the bridge from breaking.
* **Early Returns (Guard Clauses)**: Prefer early returns to handle edge cases, invalid data, or authorization checks at the top of functions. This reduces deep indentation and makes the "happy path" easier to follow.
* **Fail Fast**: Validate and parse critical configuration (like `.env` variables or required executable paths) immediately on startup into their target types (e.g., parsing `AUTHORIZED_USER_ID` safely to an integer). Exit with a clear, actionable error message if prerequisites aren't met or fail to parse, rather than throwing runtime exceptions deep in the application.
* **Actionable TODOs**: When leaving notes for future work or known issues, use a recognizable format like `TODO:` or `FIXME:` accompanied by a brief explanation.
* **Licensing**: If you create a new file, ensure it complies with the project's open-source license. (Avoid copy-pasting proprietary code into this repository).

## 2. Python Standards (Discord Bot)

* **Style Guide**: Follow [PEP 8](https://peps.python.org/pep-0008/) conventions.
* **Target Versioning**: Ensure Python code strictly targets the project's minimum supported version (Python 3.9+, as `asyncio.to_thread` is heavily used). Avoid utilizing syntax features from newer versions (like 3.10 `match`/`case`) unless the minimum requirement is officially bumped in the project documentation.
* **Naming Conventions**: Classes should use `PascalCase` (e.g., `LzyBot`), functions and variables should use `snake_case` (e.g., `active_jobs`, `run_download_job`), and module-level constants should use `UPPER_SNAKE_CASE` (e.g., `API_PORT`).
* **Type Hinting**: Use type hints (PEP 484) for all function arguments and return types to improve IDE support and catch errors early.
  ```python
  def fetch_download_status(url: str, timeout: int = 10) -> bool:
      ...
  ```
* **Strict Typing**: Treat type hints as requirements, not suggestions. Configure static analysis tools (like `mypy`) to enforce strict type checking on new code (e.g., forbidding untyped definitions).
* **Docstrings**: Write docstrings for modules, classes, and complex functions explaining *what* they do and *why*, rather than *how*. We recommend the [Google style](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings) for consistency.
* **Asynchronous Execution**: As this is a Discord bot (likely using `discord.py` or similar), ensure that blocking operations (such as long file I/O or heavy API requests) are executed asynchronously or pushed to a separate thread so the bot's main event loop is never blocked.
* **Blocking Thread Offloading**: When pushing synchronous operations (like `requests.get` or `json.dump`) out of the main event loop, prefer modern `asyncio.to_thread()` over manually managing ThreadPoolExecutors.
* **Asynchronous HTTP Clients**: Since `aiohttp` is already introduced as a dependency for the webhook server, prefer using asynchronous HTTP clients (such as `aiohttp.ClientSession` or `httpx`) for making outbound requests to the local C++ API. Avoid mixing synchronous `requests` inside `asyncio.to_thread()` blocks to unify the network stack and reduce thread-switching overhead.
* **Loop Variables in Closures**: When creating async callbacks or tasks inside a `for` loop, use factory functions or default arguments to capture loop variables immediately. This prevents Python's late-binding behavior from assigning the loop's final value to all generated callbacks.
* **Background Task Management**: When spawning "fire-and-forget" asynchronous background tasks (such as kicking off a download job), prefer using `bot.loop.create_task()` over standard `asyncio.create_task()`. This ensures the task is explicitly bound to the Discord client's event loop and lifecycle.
* **Asyncio Primitives**: Never instantiate `asyncio.Lock`, `asyncio.Event`, or `asyncio.Condition` as module-level globals. In Python 3.10+, this triggers a `DeprecationWarning` and can cause deadlocks if instantiated before the main event loop is running. Always initialize them safely inside an active loop context, such as `setup_hook`.
* **Concurrency & Shared State**: Use appropriate synchronization primitives (e.g., `asyncio.Lock()`) when reading or modifying global/shared state across concurrent async tasks to prevent race conditions.
* **Network & I/O Timeouts**: Always provide explicit `timeout` arguments when making synchronous network requests (e.g., `requests.get`) or waiting on subprocesses to prevent the application from hanging indefinitely.
* **File Handling & Encoding**: Always specify `encoding='utf-8'` when reading or writing files (e.g., reading JSON backups). This prevents unpredictable `UnicodeDecodeError` crashes on Windows, where the default system locale might not be UTF-8.
* **State Encapsulation**: Minimize the use of module-level `global` variables. As the application grows, prefer encapsulating state and locks within dedicated classes (such as the `discord.Client` subclass) to improve maintainability.
* **Signal Handling & Graceful Exit**: Ensure the bot registers proper signal handlers (e.g., for `SIGINT` and `SIGTERM`) to clean up subprocesses and release system resources (like port bindings or lock files) cleanly, even if the application is terminated abruptly or via Docker shutdown commands.
* **Platform Considerations & File Paths**: The bridge supports Windows, Linux, and macOS. Use the platform data roots that match Qt's `QStandardPaths::AppLocalDataLocation` (`LOCALAPPDATA`, XDG data, or macOS Application Support), and prefer modern Python's `pathlib.Path` over `os.path` for filesystem paths. Keep Windows-specific subprocess flags graceful (e.g., using `getattr()`), and never use Windows environment-variable syntax as a POSIX fallback.
* **Discord API Limits**: Always truncate or paginate messages that might exceed Discord's 2000-character limit (e.g., long API error logs or video titles), and handle potential rate-limit exceptions gracefully.
* **Discord Edit Debouncing**: When processing high-frequency webhook events, use a debounce mechanism (e.g., an `asyncio.sleep()` delay in the update loop) to avoid hitting Discord's aggressive message-editing rate limits.
* **Progress Field Semantics**: Treat `overall_progress` as the preferred active-display percentage for multi-stream jobs. The ordinary `progress` field is current-stream progress and may reset when yt-dlp changes streams; never let an out-of-order aggregate webhook reduce an active displayed percentage.
* **Slash Command Deferrals**: Discord slash commands must be acknowledged within **3 seconds**. If a command handler performs blocking synchronous tasks (like loading backups from disk) or checks network health before outputting its initial response, always use `await interaction.response.defer()` first to prevent "Interaction failed" errors.
* **Webhook Port Binding Failures**: When spinning up the `aiohttp` webhook server, wrap the runner and port binding sequence in an exception handler to catch port conflicts (such as `OSError` / `EADDRINUSE`). This prevents cryptic traceback dumps if a zombie bot process is already holding the webhook port.
* **Discord UX / Messages**: Standardize user-facing Discord messages by prefixing them with consistent emojis (e.g., ⏳ for progress, ✅ for success, ❌ for errors) to provide quick visual status cues.
* **Command Interfaces**: Prefer Discord Slash Commands (`app_commands`) over legacy text-prefix commands. They provide better user discoverability, built-in parameter validation, and a cleaner UX.
* **Command Limits**: Keep Slash Command (`app_commands`) descriptions concise and strictly under Discord's 100-character limit.
* **Markdown Sanitization**: Dynamic content received from external sources (like video titles or API error messages) must be sanitized using `discord.utils.escape_markdown()` to prevent UI breakage or unintended formatting (e.g., malicious spoiler tags).
* **Actionable User Errors**: When surfacing errors to Discord (such as a failure to reach the C++ application), try to include actionable troubleshooting steps (e.g., "Check if LzyDownloader is installed") alongside the raw error string to assist the user.
* **Magic Numbers**: Avoid hardcoding obscure constants (e.g., arbitrary timeouts like `43200` or socket ports like `48765`) deep in the code. Extract these to clearly named constant variables at the top of the module.
* **String Formatting**: Prefer modern Python f-strings (e.g., `f"{BASE_URL}/status"`) over older `%` formatting or `.format()` for readability.
* **Regular Expressions**: For performance, especially within high-frequency event handlers like webhooks, compile regex patterns at the module level using `re.compile()` rather than evaluating them dynamically inside functions or loops.
* **Import Organization**: Group imports logically: standard library first, followed by third-party packages, and finally local modules. (Using `isort` automates this).
* **Environment Management**: Use a virtual environment (e.g., `python -m venv venv`) to manage dependencies.
* **Dependencies**: Maintain an up-to-date `requirements.txt`. Pin versions for production stability when appropriate, and test thoroughly before upgrading foundational packages (like `discord.py` or `requests`).
* **Adding New Libraries**: Before adding new third-party dependencies, evaluate them for necessity, bloat, and security. Standard library solutions are preferred for simple tasks.
* **Tooling**: We recommend using `black` (with a standard line length of 88 or 100) for auto-formatting, `isort` (configured with `--profile black`) for import sorting, `flake8` for linting, and `mypy` for static type checking. Consider using `pre-commit` hooks to enforce these automatically before changes are pushed.

## 3. Batch Script Standards (`.bat`)

* **Comments**: Use the double-colon `::` for comments instead of `REM` as it is generally cleaner and processes slightly faster.
* **Clean Output**: Always start scripts with `@echo off`.
* **User Feedback**: Provide clear execution feedback using `echo` so the user knows exactly what state the script is in (e.g., "Stopping existing instances...").
* **Error Suppression**: When targeting processes that might not exist, gracefully suppress output using `>nul 2>&1` to avoid alarming the user with benign error text.

## 4. C++ Standards (LzyDownloader Core)

If your contributions extend into the `LzyDownloader.exe` C++ backend:

* **Modern C++**: Target C++17 or newer. Use modern language features (e.g., `auto`, range-based for loops, structured bindings).
* **Memory Management**: Strictly avoid raw `new`/`delete`. Rely on RAII, use smart pointers (`std::unique_ptr`, `std::shared_ptr`), and leverage Qt6's object tree mechanism (passing `parent` pointers) for `QObject` lifecycles.
* **Naming Conventions**:
  * **Classes/Structs**: `PascalCase` (e.g., `DownloadManager`)
  * **Functions/Methods**: `camelCase` (e.g., `startDownload`)
  * **Variables**: `snake_case` (e.g., `file_size`)
  * **Constants/Macros**: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRY_COUNT`)
* **Qt6 specifics**: When communicating between background download tasks and the local API web server, rely on Qt6's signal/slot mechanism for thread-safe data passing. Always use the modern, pointer-based `connect` syntax rather than the legacy `SIGNAL()`/`SLOT()` macros to ensure compile-time type safety.
* **Non-Blocking Event Loop**: Never execute heavy disk I/O, network downloads, or blocking system calls on the main Qt GUI/Event thread. Rely on `QtConcurrent`, worker `QThread` instances, or asynchronous signals to ensure the local HTTP API remains highly responsive to the Python bridge.
* **Tooling**: We recommend using `clang-format` to maintain consistent code formatting and `clang-tidy` for static analysis to catch potential C++ bugs early.

## 5. Version Control (Git)

* **Commit Messages**: 
  * We recommend the [Conventional Commits](https://www.conventionalcommits.org/) standard (e.g., `feat:`, `fix:`, `chore:`).
  * Start the description with a capitalized, imperative verb (e.g., "feat: Add support for audio").
  * Keep the subject line concise (under 50 characters).
  * Use the body of the commit to explain the *why* if the change is complex.
* **Versioning**: We follow [Semantic Versioning](https://semver.org/) (MAJOR.MINOR.PATCH) for releases and git tags.
* **Branching**: Do your work in feature branches and open a Pull Request against the main branch for review.
* **Pull Requests**:
  * If the repository contains a Pull Request template, please fill it out completely.
  * Provide a clear description of the problem being solved and how the PR fixes it.
  * Link any relevant issues or feature requests.
  * Self-review your code and ensure manual tests pass before requesting a review.
* **Line Endings**: Given the mix of Python/C++ code and Windows `.bat` scripts, rely on a `.gitattributes` file to enforce `LF` for source code and `CRLF` for batch scripts. Ensure your IDE respects these line endings.

## 6. Testing & Quality Assurance

* **Manual Verification**: Since this involves UI/Discord interactions, ensure you test end-to-end flows (e.g., starting a download, receiving progress updates, handling errors) before opening a PR.
* **Edge Cases**: Always test edge cases, such as invalid URLs, network timeouts, or the C++ server being forcefully closed during a download.
* **Automated Testing**: As the project scales, prefer writing unit tests (e.g., using `pytest`) for pure logic modules (like URL validation, URL expansion mapping, and JSON backup parsing) to prevent regressions.
* **Test Isolation & Mocking**: All automated tests must run in total isolation. External network requests, file-system I/O for system directories, and subprocess spawns must be mocked (e.g., using `unittest.mock` or `pytest-mock`) to avoid side effects and allow tests to run offline or in CI/CD environments.
* **Continuous Integration (CI)**: Ensure that your code passes all automated linting (`flake8`, `black`, `isort`) and static type checks (`mypy`) before submitting a PR.

## 7. Security & Community

* **Never commit secrets**: API keys, Discord bot tokens, and user credentials must never be committed to the repository. Use `.env` files and ensure `.env` is listed in your `.gitignore`.
* **Sensitive Data in Logs**: Avoid logging sensitive information, such as API tokens, authorized user IDs, or potentially private URLs requested by users in DMs.
* **Documenting Configuration**: If you introduce a new required environment variable to the project, you must document it in `README.md` and add a dummy value for it in the project's `.env.example` file to maintain a smooth onboarding experience.
* **Least Privilege (Discord)**: Run the bot with the minimum necessary Discord permissions. Only request Gateway Intents (like Message Content) that are actively required for the bot's documented features.
* **Vulnerability Reporting**: If you discover a security vulnerability (e.g., path traversal, arbitrary execution), do not open a public issue. Instead, report it privately to the maintainers (e.g., via GitHub Security Advisories).
* **Code of Conduct**: All contributors are expected to follow the project's Code of Conduct. Be respectful and constructive during code reviews.
