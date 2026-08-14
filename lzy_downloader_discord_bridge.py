import os
import re
import asyncio
import json
import socket
import sys
import time
import subprocess
import atexit
import logging
from logging.handlers import RotatingFileHandler
import requests
import discord
from discord import app_commands
from aiohttp import web
from dotenv import load_dotenv
from urllib.parse import urlparse
from typing import Optional, Callable, Awaitable, Any, Dict, List, Set, Tuple

APP_VERSION: str = "1.2.9"

# Load the Discord token from the .env file located in the script's directory
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')

# The normal launcher uses pythonw, so console output is unavailable in the
# background. Keep bridge, library, and uncaught-exception diagnostics in a
# bounded file beside this script.
LOG_PATH = os.path.join(script_dir, 'bot.log')

class TimestampedRotatingFileHandler(RotatingFileHandler):
    """Rotate by size and give archived files an unambiguous timestamp."""
    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None

        timestamp = time.strftime('%Y-%m-%d_%H-%M-%S')
        archive_path = os.path.join(script_dir, f'bot_{timestamp}.log')
        suffix = 1
        while os.path.exists(archive_path):
            archive_path = os.path.join(script_dir, f'bot_{timestamp}_{suffix}.log')
            suffix += 1
        if os.path.exists(self.baseFilename):
            os.replace(self.baseFilename, archive_path)

        self.stream = self._open()
        archived_logs = sorted(
            (os.path.join(script_dir, name) for name in os.listdir(script_dir)
             if name.startswith('bot_') and name.endswith('.log')),
            key=os.path.getmtime,
            reverse=True,
        )
        for old_log in archived_logs[self.backupCount:]:
            try:
                os.remove(old_log)
            except OSError:
                pass

logger = logging.getLogger('lzy_downloader_discord_bridge')
logger.setLevel(logging.INFO)
file_handler = TimestampedRotatingFileHandler(LOG_PATH, maxBytes=10 * 1024 * 1024,
                                               backupCount=5, encoding='utf-8')
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'))
logger.addHandler(file_handler)

if sys.__stderr__ is not None:
    console_handler = logging.StreamHandler(sys.__stderr__)
    console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    logger.addHandler(console_handler)

for library_name in ('discord', 'aiohttp', 'asyncio'):
    library_logger = logging.getLogger(library_name)
    library_logger.setLevel(logging.INFO)
    library_logger.addHandler(file_handler)

def log_uncaught_exception(exc_type: type[BaseException], exc_value: BaseException,
                           exc_traceback: Any) -> None:
    """Write an uncaught exception before the background process exits."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical('Uncaught exception', exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = log_uncaught_exception
logger.info('Bridge logging initialized. Log file: %s', LOG_PATH)

class _LoggingOutput:
    """Route legacy print output through the rotating logger."""
    def __init__(self, level: int) -> None:
        self.level = level
        self.buffer = ''

    def write(self, text: str) -> int:
        self.buffer += text
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            if line:
                logger.log(self.level, line)
        return len(text)

    def flush(self) -> None:
        if self.buffer:
            logger.log(self.level, self.buffer)
            self.buffer = ''

sys.stdout = _LoggingOutput(logging.INFO)
sys.stderr = _LoggingOutput(logging.ERROR)
load_dotenv(dotenv_path=env_path)
TOKEN: Optional[str] = os.getenv('DISCORD_BOT_TOKEN')
AUTHORIZED_USER_ID: Optional[str] = os.getenv('AUTHORIZED_USER_ID')

# LzyDownloader Local API Settings
API_PORT: int = 8765
BASE_URL: str = f"http://127.0.0.1:{API_PORT}"
BACKUP_ARCHIVE_RETENTION: int = 2

# Load from .env
LZY_EXECUTABLE_PATH: Optional[str] = os.getenv('LZY_EXECUTABLE_PATH')

# Pre-compiled regexes for high-frequency webhook parsing
YOUTUBE_ID_REGEX = re.compile(r"(?:youtu\.be/|v=|/shorts/|/live/)([0-9A-Za-z_-]{11})(?:\?|&|/|$)")
NORMALIZE_URL_REGEX = re.compile(r"^https?://(www\.)?")
QUEUE_POSITION_REGEX = re.compile(r"\s*\(Position:?\s*\d+\)", re.IGNORECASE)

# Global reference to prevent the socket from being garbage collected
_lock_socket: Optional[socket.socket] = None
_lzy_process: Optional[subprocess.Popen] = None

def enforce_single_instance() -> None:
    """Binds a local UDP socket to prevent multiple instances of the bot."""
    global _lock_socket
    _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        _lock_socket.bind(('127.0.0.1', 48765))  # Arbitrary dedicated port for the lock
    except socket.error:
        print(
            "❌ Another instance of the LzyDownloader Discord Bridge "
            "is already running. Exiting."
        )
        sys.exit(1)

def cleanup_subprocess() -> None:
    """Ensures the headless LzyDownloader process is terminated when the bot exits."""
    global _lzy_process
    if _lzy_process and _lzy_process.poll() is None:
        print("🛑 Terminating headless LzyDownloader process...")
        try:
            _lzy_process.terminate()
            _lzy_process.wait(timeout=3)
        except Exception:
            pass

atexit.register(cleanup_subprocess)

def is_valid_url(url: str) -> bool:
    """Validates that a string is a properly formatted HTTP/HTTPS URL."""
    try:
        result = urlparse(url)
        return result.scheme in ('http', 'https') and bool(result.netloc)
    except Exception:
        return False

def create_progress_bar(progress: Any, length: int = 20) -> str:
    """Generates an ASCII progress bar for Discord messages."""
    try:
        if isinstance(progress, str):
            progress = progress.replace("%", "").strip()
        progress_val = float(progress)
    except (ValueError, TypeError):
        progress_val = 0.0
        
    progress_val = max(0.0, min(100.0, progress_val))
    filled_length = int(length * progress_val // 100)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"`[{bar}] {progress_val:.1f}%`"

class LzyBot(discord.Client):
    def __init__(self) -> None:
        # Enable the message content intent so we can read DM text
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.active_jobs: Dict[str, Dict[str, Any]] = {}
        self.tree = app_commands.CommandTree(self)
        
        # State encapsulated to the bot instance
        self.launch_lock: Optional[asyncio.Lock] = None
        self.jobs_lock: Optional[asyncio.Lock] = None
        self.recovery_lock: Optional[asyncio.Lock] = None
        self.active_job_count: int = 0
        self.startup_resume_started: bool = False

    async def setup_hook(self) -> None:
        # Initialize locks within the active event loop
        self.launch_lock = asyncio.Lock()
        self.jobs_lock = asyncio.Lock()
        self.recovery_lock = asyncio.Lock()

        # Sync the slash commands to Discord when the bot starts
        await self.tree.sync()
        
        # Start the local webhook server to listen for C++ push updates
        app = web.Application()
        app.router.add_post('/webhook', self.handle_webhook)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 8766)
        await site.start()
        print("Local webhook server listening on 127.0.0.1:8766")
        
        print("Bot is online and slash commands are synced!")

    async def handle_webhook(self, request: web.Request) -> web.Response:
        """Handles push updates from the C++ application."""
        try:
            data = await request.json()
            print(f"[Webhook IN] {data}")
        except Exception as e:
            print(f"[Webhook ERROR] Failed to parse JSON: {e}")
            return web.Response(status=400, text="Invalid JSON")
            
        # Catch multiple common casing formats just in case
        job_key = data.get("job_id") or data.get("id") or data.get("jobId") or data.get("lzy_id")
        if not job_key:
            print("[Webhook ERROR] Rejected payload: Missing job ID.")
            return web.Response(status=400, text="Missing job_id in webhook payload")
        
        job_key = str(job_key)
        
        if job_key not in self.active_jobs:
            # The C++ app might have expanded a URL and changed the job ID (e.g., PlaylistExpander).
            # Attempt to re-key the job using parent_id or fuzzy URL matching.
            webhook_parent = data.get("parent_id")
            webhook_url = data.get("url", "")
            found_key = None
            
            if webhook_parent and str(webhook_parent) in self.active_jobs:
                found_key = str(webhook_parent)
            elif webhook_url:
                def normalize_url(u: str) -> str:
                    return NORMALIZE_URL_REGEX.sub("", u).rstrip("/")
                    
                incoming_norm = normalize_url(webhook_url)
                yt_id_incoming = None
                if "youtu" in webhook_url:
                    m = YOUTUBE_ID_REGEX.search(webhook_url)
                    if m:
                        yt_id_incoming = m.group(1)
                        
                for existing_key, existing_data in list(self.active_jobs.items()):
                    tracked_url = existing_data.get("url", "")
                    
                    if yt_id_incoming and "youtu" in tracked_url:
                        m2 = YOUTUBE_ID_REGEX.search(tracked_url)
                        if m2 and m2.group(1) == yt_id_incoming:
                            found_key = existing_key
                            break
                            
                    tracked_norm = normalize_url(tracked_url)
                    if tracked_norm and (tracked_norm in incoming_norm or incoming_norm in tracked_norm):
                        found_key = existing_key
                        break
            
            if found_key:
                print(f"[Webhook] Routing child ID {job_key} updates to parent job {found_key}")
                job_key = found_key
            else:
                print(f"[Webhook ERROR] Rejected payload: Job {job_key} not tracked by bridge.")
                return web.Response(status=404, text="Job not tracked by bridge")
            
        job_data = self.active_jobs[job_key]
        
        # Only update fields that are actually provided in this specific webhook payload
        if "status" in data and data["status"]:
            job_data["status_text"] = data["status"]
            
        if "queue_position" in data:
            job_data["queue_position"] = data["queue_position"]
            
        if "progress" in data and data["progress"] is not None:
            job_data["progress"] = data["progress"]
            
        if "speed" in data and data["speed"] is not None:
            job_data["speed"] = data["speed"]
            
        if "eta" in data and data["eta"] is not None:
            job_data["eta"] = data["eta"]
            
        if "title" in data and data["title"]:
            job_data["title"] = data["title"]
            
        current_status = str(job_data["status_text"]).lower()
        if current_status in {"completed", "complete", "failed", "stopped", "finished", "error"}:
            job_data["is_final"] = True
            job_data["final_status"] = current_status
            
        job_data["last_webhook_time"] = time.time()
            
        return web.Response(text="OK")

    async def on_ready(self) -> None:
        print(f"Discord connection ready as {self.user}.")
        # Arm recovery tracking before missed-DM tasks can launch the worker.
        await resume_backed_up_downloads_on_startup()

        if AUTHORIZED_USER_ID:
            try:
                user = await self.fetch_user(int(AUTHORIZED_USER_ID))
                await user.send("🟢 **LzyDownloader Discord Bridge is now online!**")

                # Check for missed DMs sent while the bot was offline
                dm_channel = await user.create_dm()
                messages = [m async for m in dm_channel.history(limit=20)]

                # Load backup items to prevent duplicate queueing of resumed downloads
                backup_items = load_download_backup_items()
                resumed_urls = {item.get("url") for item in backup_items if item.get("url")}

                missed_msgs = []
                for i, msg in enumerate(messages):
                    if msg.author.id == int(AUTHORIZED_USER_ID):
                        content = msg.content.strip()
                        if is_valid_url(content):
                            # Skip if this URL is already slated to be resumed/tracked
                            if content in resumed_urls or any(content in url or url in content for url in resumed_urls):
                                continue

                            # Check if the bot already replied to this specific request
                            # Since history is newest-to-oldest, newer messages are at indices < i
                            bot_replied = any(
                                (newer_msg.author == self.user and content in newer_msg.content)
                                for newer_msg in messages[:i]
                            )
                            if not bot_replied:
                                missed_msgs.append(msg)

                # Create closure-safe callbacks for our background task
                def create_callbacks(s_msg: discord.Message, chan: discord.abc.Messageable):
                    async def edit_callback(new_content: str) -> None:
                        await s_msg.edit(content=new_content)
                    async def send_callback(new_content: str) -> None:
                        await chan.send(new_content)
                    return edit_callback, send_callback

                # Process oldest missed messages first
                for msg in reversed(missed_msgs):
                    content = msg.content.strip()
                    sent_msg = await msg.channel.send(
                        f"⏳ **Missed offline request detected. Starting download:** <{content}>\n"
                        "*Running in background...*"
                    )
                    
                    edit_msg_cb, send_msg_cb = create_callbacks(sent_msg, msg.channel)
                    self.loop.create_task(run_download_job(content, edit_msg_cb, send_msg_cb))

            except Exception as e:
                print(f"Failed to process startup DM or missed messages: {e}")

    async def on_resumed(self) -> None:
        """Logs successful gateway recovery after a network interruption or wake."""
        print("Discord gateway session resumed after interruption.")

    async def on_disconnect(self) -> None:
        """Logs gateway loss; discord.py will attempt its built-in reconnect."""
        print("Discord gateway disconnected; waiting for automatic reconnect.")

    async def close(self) -> None:
        if AUTHORIZED_USER_ID:
            try:
                user = await self.fetch_user(int(AUTHORIZED_USER_ID))
                await user.send("🔴 **LzyDownloader Discord Bridge is now offline.**")
            except Exception as e:
                print(f"Failed to send shutdown DM: {e}")
        cleanup_subprocess()
        await super().close()

    async def on_message(self, message: discord.Message) -> None:
        # Ignore messages from bots or messages in guilds (servers)
        if message.author.bot or message.guild is not None:
            return

        # Strictly enforce authorization
        if str(message.author.id) != AUTHORIZED_USER_ID:
            return

        content = message.content.strip()
        if content.lower() in ["ping", "/ping"]:
            await message.channel.send("🏓 Pong! LzyDownloader Discord Bridge is online.")
            return

        if is_valid_url(content):
            sent_msg = await message.channel.send(
                f"⏳ **Starting download:** <{content}>\n"
                "*Running in background...*"
            )
            
            async def edit_msg(new_content: str) -> None:
                await sent_msg.edit(content=new_content)
                
            async def send_msg(new_content: str) -> None:
                await message.channel.send(new_content)
                
            self.loop.create_task(run_download_job(content, edit_msg, send_msg))

client = LzyBot()

@client.tree.command(name="ping", description="Ping the bot to check its status")
async def ping(interaction: discord.Interaction) -> None:
    if str(interaction.user.id) != AUTHORIZED_USER_ID:
        await interaction.response.send_message("❌ Unauthorized.", ephemeral=True)
        return
    await interaction.response.send_message("🏓 Pong! LzyDownloader Discord Bridge is online.")

@client.tree.command(name="stop", description="Gracefully shut down the Discord bot")
async def stop(interaction: discord.Interaction) -> None:
    if str(interaction.user.id) != AUTHORIZED_USER_ID:
        await interaction.response.send_message("❌ Unauthorized.", ephemeral=True)
        return
    await interaction.response.send_message("🛑 Shutting down the bot gracefully...")
    await client.close()

@client.tree.command(name="help", description="List all available commands")
async def help_cmd(interaction: discord.Interaction) -> None:
    if str(interaction.user.id) != AUTHORIZED_USER_ID:
        await interaction.response.send_message("❌ Unauthorized.", ephemeral=True)
        return
        
    commands = client.tree.get_commands()
    help_text = "**Available Commands:**\n"
    for cmd in commands:
        if isinstance(cmd, app_commands.Command):
            help_text += f"`/{cmd.name}` - {cmd.description}\n"
        
    await interaction.response.send_message(help_text, ephemeral=True)

@client.tree.command(name="download", description="Start a new download")
@app_commands.describe(url="The URL of the media to download")
async def download(interaction: discord.Interaction, url: str) -> None:
    if str(interaction.user.id) != AUTHORIZED_USER_ID:
        await interaction.response.send_message("❌ Unauthorized.", ephemeral=True)
        return
        
    if not is_valid_url(url):
        await interaction.response.send_message(
            "❌ Invalid URL provided. Please provide a valid HTTP/HTTPS link.", 
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"⏳ **Starting download:** <{url}>\n"
        "*Running in background...*"
    )
    sent_msg = await interaction.original_response()
    
    async def edit_msg(new_content: str) -> None:
        await sent_msg.edit(content=new_content)
            
    async def send_msg(new_content: str) -> None:
        if isinstance(interaction.channel, discord.abc.Messageable):
            if interaction.guild is not None:
                await interaction.channel.send(f"{interaction.user.mention} {new_content}")
            else:
                await interaction.channel.send(new_content)
            
    client.loop.create_task(run_download_job(url, edit_msg, send_msg))

@client.tree.command(name="audio", description="Start a new audio-only download")
@app_commands.describe(url="The URL of the media to download as audio")
async def audio(interaction: discord.Interaction, url: str) -> None:
    if str(interaction.user.id) != AUTHORIZED_USER_ID:
        await interaction.response.send_message("❌ Unauthorized.", ephemeral=True)
        return
        
    if not is_valid_url(url):
        await interaction.response.send_message(
            "❌ Invalid URL provided. Please provide a valid HTTP/HTTPS link.", 
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"⏳ **Starting audio download:** <{url}>\n"
        "*Running in background...*"
    )
    sent_msg = await interaction.original_response()
    
    async def edit_msg(new_content: str) -> None:
        await sent_msg.edit(content=new_content)
            
    async def send_msg(new_content: str) -> None:
        if isinstance(interaction.channel, discord.abc.Messageable):
            if interaction.guild is not None:
                await interaction.channel.send(f"{interaction.user.mention} {new_content}")
            else:
                await interaction.channel.send(new_content)
            
    client.loop.create_task(run_download_job(url, edit_msg, send_msg, download_type="audio"))

@client.tree.command(name="clear_failed", description="Clear failed recovery jobs from the backup file")
async def clear_failed(interaction: discord.Interaction) -> None:
    if str(interaction.user.id) != AUTHORIZED_USER_ID:
        await interaction.response.send_message("❌ Unauthorized.", ephemeral=True)
        return

    removed_count, kept_count, archive_path = clear_failed_backup_items()
    if removed_count == 0:
        await interaction.response.send_message(
            "No inactive (failed/stopped/completed) recovery jobs were found in `downloads_backup.json`.",
            ephemeral=True
        )
        return

    message = (
        f"Cleared {removed_count} inactive job(s) from "
        "`downloads_backup.json`."
    )
    if kept_count:
        message += f"\nKept {kept_count} queued resumable job(s)."
    else:
        message += "\nNo queued resumable jobs remain."
    if archive_path:
        message += f"\nArchived the previous backup as `{archive_path}`."

    await interaction.response.send_message(message, ephemeral=True)

@client.tree.command(name="retry_failed", description="Retry failed recovery jobs without restarting the bot")
async def retry_failed(interaction: discord.Interaction) -> None:
    if str(interaction.user.id) != AUTHORIZED_USER_ID:
        await interaction.response.send_message("❌ Unauthorized.", ephemeral=True)
        return

    backup_file_path = get_download_backup_path()
    retry_count = sum(
        1 for item in load_download_backup_items()
        if should_retry_backup_item(item)
    )
    if retry_count == 0:
        await interaction.response.send_message(
            f"No failed or stopped recovery jobs were found in `{backup_file_path}`.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"Retrying {retry_count} failed/stopped recovery job(s). "
        "I will DM progress updates.",
        ephemeral=True
    )
    client.loop.create_task(
        resume_backed_up_downloads_on_startup(force=True, user=interaction.user)
    )

def get_lzy_api_key() -> Optional[str]:
    """Reads the auto-generated API key from LzyDownloader's AppData folder.
    Checks both Server and GUI token files and returns the one that successfully authorizes."""
    server_dir = get_lzy_server_data_dir()
    gui_dir = os.path.dirname(server_dir)
    
    keys_to_try = []
    for d in [server_dir, gui_dir]:
        key_path = os.path.join(d, 'api_token.txt')
        if os.path.exists(key_path):
            try:
                with open(key_path, 'r', encoding='utf-8') as f:
                    val = f.read().strip()
                    if val:
                        keys_to_try.append(val)
            except OSError:
                pass
                
    if not keys_to_try:
        return None
        
    proxies = {"http": "", "https": ""}
    for key in keys_to_try:
        try:
            headers = {"Authorization": f"Bearer {key}"}
            res = requests.get(f"{BASE_URL}/status", headers=headers, timeout=1, proxies=proxies)
            if res.status_code == 200:
                return key
        except requests.exceptions.RequestException:
            pass
            
    return keys_to_try[0]


def get_lzy_server_data_dir() -> str:
    """Returns the LzyDownloader data directory used by --server launches."""
    app_data = os.getenv('LOCALAPPDATA')
    if not app_data:
        # Fallback to standard Windows path expansion if environment variable is missing
        app_data = os.path.expandvars(r'%USERPROFILE%\AppData\Local')
    return os.path.join(app_data, 'LzyDownloader', 'Server')


def get_download_backup_path() -> str:
    """Returns the server-mode queue backup file used by LzyDownloader."""
    return os.path.join(get_lzy_server_data_dir(), 'downloads_backup.json')


def prune_backup_archives() -> None:
    """Keeps only the newest backup archive files created by the Discord bridge."""
    backup_path = get_download_backup_path()
    backup_dir = os.path.dirname(backup_path)
    backup_name = os.path.basename(backup_path)
    if not os.path.isdir(backup_dir):
        return

    archive_names = [
        name for name in os.listdir(backup_dir)
        if (
            name.startswith(f"{backup_name}.discord_recovery_")
            or name.startswith(f"{backup_name}.cleared_failed_")
        )
        and name.endswith(".bak")
    ]
    archive_paths = [os.path.join(backup_dir, name) for name in archive_names]
    archive_paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)

    for old_archive in archive_paths[BACKUP_ARCHIVE_RETENTION:]:
        try:
            os.remove(old_archive)
        except OSError as e:
            print(f"Could not prune old backup archive {old_archive}: {e}")


def load_download_backup_items() -> List[Dict[str, Any]]:
    """Reads resumable server-mode downloads from LzyDownloader's backup file."""
    backup_path = get_download_backup_path()
    if not os.path.exists(backup_path):
        return []

    try:
        with open(backup_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(data, list):
        return []

    return [item for item in data if isinstance(item, dict)]


def get_backup_item_download_type(item: Dict[str, Any]) -> str:
    """Returns the download type stored in a backup item or API response."""
    options = item.get("options")
    if isinstance(options, dict):
        return str(options.get("type") or "video")
    return str(item.get("download_type") or item.get("type") or "video")


def find_backup_item(url: str, download_type: str) -> Optional[Dict[str, Any]]:
    """Finds a matching item in the current server-mode backup file."""
    for item in load_download_backup_items():
        item_url = str(item.get("url", ""))
        if (
            (url in item_url or item_url in url)
            and get_backup_item_download_type(item) == download_type
        ):
            return item
    return None


def should_retry_backup_item(item: Dict[str, Any]) -> bool:
    """Returns true for backed-up items that LzyDownloader will not auto-run."""
    status = str(item.get("status", "queued")).lower()
    options = item.get("options")
    if not isinstance(options, dict):
        options = {}

    return bool(item.get("url")) and (
        status in {"stopped", "failed", "error"}
        or bool(options.get("is_failed"))
        or bool(options.get("is_stopped"))
    )

def is_completed_backup_item(item: Dict[str, Any]) -> bool:
    """Returns true for backed-up items that have already completed."""
    status = str(item.get("status", "")).lower()
    options = item.get("options")
    if not isinstance(options, dict):
        options = {}

    if status in {"error", "failed", "stopped"}:
        return False
    if bool(options.get("is_failed")) or bool(options.get("is_stopped")):
        return False

    if status in {"completed", "complete", "finished", "downloaded", "done", "success"}:
        return True
    if bool(options.get("is_finished")) or bool(options.get("is_completed")):
        return True

    progress = item.get("progress")
    try:
        if progress is not None and float(progress) >= 100.0:
            return True
    except (ValueError, TypeError):
        pass

    return False


def prepare_download_backup_for_recovery(
    retry_items: List[Dict[str, Any]],
    keep_items: List[Dict[str, Any]]
) -> None:
    """Prevents stopped backup entries from blocking fresh recovery enqueues."""
    if not retry_items:
        return

    backup_path = get_download_backup_path()
    if not os.path.exists(backup_path):
        return

    stamp = time.strftime("%Y%m%d_%H%M%S")
    archive_path = f"{backup_path}.discord_recovery_{stamp}.bak"
    try:
        os.replace(backup_path, archive_path)
        print(f"Archived stranded download backup to {archive_path}")
        prune_backup_archives()
    except OSError as e:
        print(f"Could not archive stranded download backup: {e}")
        return

    if keep_items:
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(keep_items, f, indent=4)
        except OSError as e:
            print(f"Could not rewrite remaining download backup items: {e}")


def clear_failed_backup_items() -> Tuple[int, int, Optional[str]]:
    """Removes failed/stopped jobs from downloads_backup.json after archiving it."""
    backup_path = get_download_backup_path()
    items = load_download_backup_items()
    if not items or not os.path.exists(backup_path):
        return 0, 0, None

    failed_items = [item for item in items if should_retry_backup_item(item)]
    completed_items = [item for item in items if is_completed_backup_item(item)]
    kept_items = [
        item for item in items
        if item.get("url") and not should_retry_backup_item(item) and not is_completed_backup_item(item)
    ]
    if not failed_items and not completed_items:
        return 0, len(kept_items), None

    stamp = time.strftime("%Y%m%d_%H%M%S")
    archive_path = f"{backup_path}.cleared_failed_{stamp}.bak"
    try:
        os.replace(backup_path, archive_path)
        prune_backup_archives()
    except OSError as e:
        print(f"Could not archive failed download backup: {e}")
        return 0, len(kept_items), None

    if kept_items:
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                json.dump(kept_items, f, indent=4)
        except OSError as e:
            print(f"Could not rewrite remaining backup items: {e}")
            return len(failed_items) + len(completed_items), len(kept_items), archive_path

    return len(failed_items) + len(completed_items), len(kept_items), archive_path


def check_api_health() -> None:
    """Checks if the Local API is responding. If not, launches the app and waits for it."""
    global _lzy_process

    proxies = {"http": "", "https": ""}

    # First, try a quick ping to see if it's already running
    try:
        api_key = get_lzy_api_key()
        if api_key:
            headers = {"Authorization": f"Bearer {api_key}"}
            res = requests.get(
                f"{BASE_URL}/status", headers=headers, timeout=2, proxies=proxies
            )
            if res.status_code == 200:
                return  # It's running and authorized, we're good.
    except requests.exceptions.ConnectionError:
        pass  # App is not running, proceed to launch logic.
    except requests.exceptions.RequestException:
        pass  # Some other issue, but we'll try re-launching anyway.

    # If we're here, the app is not running or not responding correctly. Launch it.
    if not LZY_EXECUTABLE_PATH or not os.path.exists(LZY_EXECUTABLE_PATH):
        raise RuntimeError(
            "**LzyDownloader Not Found.**\nExecutable not found at the "
            f"configured path:\n`{LZY_EXECUTABLE_PATH}`\n\n"
            "Please ensure `LZY_EXECUTABLE_PATH` is set correctly in your `.env` file."
        )

    # Clean up any stale token from a previous run so we don't try to use it
    key_path = os.path.join(get_lzy_server_data_dir(), 'api_token.txt')
    if os.path.exists(key_path):
        try:
            os.remove(key_path)
        except OSError:
            pass

    print("LzyDownloader not detected. Launching in server mode...")
    app_dir = os.path.dirname(LZY_EXECUTABLE_PATH)
    # CREATE_NO_WINDOW flag prevents a console from flashing on Windows
    creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    _lzy_process = subprocess.Popen(
        [LZY_EXECUTABLE_PATH, "--server", "--exit-after"], 
        cwd=app_dir, 
        creationflags=creation_flags
    )

    # Now, poll for it to become ready
    last_error = "Timed out."
    for _ in range(20):  # Poll for up to 20 seconds
        time.sleep(1)
        
        if _lzy_process.poll() is not None:
            raise RuntimeError(
                f"**LzyDownloader crashed or closed immediately.** Exit code: {_lzy_process.returncode}.\n"
                "Try running the .exe manually in a command prompt to check for missing DLLs."
            )

        try:
            # It's crucial to re-read the key in case the app just generated a new one
            api_key = get_lzy_api_key()
            if not api_key:
                last_error = "Waiting for api_token.txt to be created..."
                continue

            headers = {"Authorization": f"Bearer {api_key}"}
            res = requests.get(
                f"{BASE_URL}/status", headers=headers, timeout=2, proxies=proxies
            )
            if res.status_code == 200:
                return  # It's running and authorized, we're good.
            last_error = f"API returned status {res.status_code}"
        except requests.exceptions.RequestException as e:
            last_error = str(e)

    raise RuntimeError(
        f"**LzyDownloader failed to launch or respond.**\nLast error: {last_error}"
    )


def build_active_job_data(url: str) -> Dict[str, Any]:
    """Creates the initial event-driven state for a tracked download."""
    return {
        "url": url,
        "status_text": "Processing",
        "queue_position": None,
        "progress": 0.0,
        "speed": "",
        "eta": "",
        "title": "",
        "is_final": False,
        "final_status": "",
        "last_content": "",
        "last_webhook_time": time.time(),
    }


async def register_active_job(job_key: str, url: str) -> bool:
    """Registers a job before launch so restored webhook events cannot be lost."""
    if job_key in client.active_jobs:
        return False

    client.active_jobs[job_key] = build_active_job_data(url)
    async with client.jobs_lock:
        client.active_job_count += 1
    return True


async def unregister_active_job(job_key: str) -> None:
    """Removes a tracked job and keeps the active-job count consistent."""
    if job_key in client.active_jobs:
        del client.active_jobs[job_key]

    async with client.jobs_lock:
        client.active_job_count = max(0, client.active_job_count - 1)


async def resume_backed_up_downloads_on_startup(
    force: bool = False,
    user: Any = None
) -> None:
    """Resumes tracking of backed up downloads or retries failed ones."""
    async with client.recovery_lock:
        if not force and client.startup_resume_started:
            return
        if not force:
            client.startup_resume_started = True

        items = await asyncio.to_thread(load_download_backup_items)
        if not items:
            return

        if force:
            retry_items = [item for item in items if should_retry_backup_item(item)]
            keep_items = [
                item for item in items
                if item.get("url") and not should_retry_backup_item(item) and not is_completed_backup_item(item)
            ]
            if not retry_items:
                return

            await asyncio.to_thread(
                prepare_download_backup_for_recovery, retry_items, keep_items
            )
            target_items = retry_items
            prefix = "🔄 **Retrying failed recovery job:**"
            skip_enqueue = False
        else:
            # Automatically prune completed jobs from the backup file on startup
            completed_items = [item for item in items if is_completed_backup_item(item)]
            if completed_items:
                keep_startup_items = [item for item in items if not is_completed_backup_item(item)]
                try:
                    def _prune_startup():
                        with open(get_download_backup_path(), 'w', encoding='utf-8') as f:
                            json.dump(keep_startup_items, f, indent=4)
                    await asyncio.to_thread(_prune_startup)
                    print(f"Pruned {len(completed_items)} completed item(s) from backup on startup.")
                except Exception as e:
                    print(f"Could not prune completed items on startup: {e}")

            target_items = [
                item for item in items 
                if not should_retry_backup_item(item) and not is_completed_backup_item(item) and item.get("url")
            ]
            if not target_items:
                return
            prefix = "🔄 **Resuming progress tracking:**"
            skip_enqueue = True

        if user is None and AUTHORIZED_USER_ID:
            try:
                user = await client.fetch_user(int(AUTHORIZED_USER_ID))
            except Exception:
                pass

        if user is None:
            return

        try:
            dm_channel = await user.create_dm()
        except Exception as e:
            print(f"Could not create DM channel for recovery tracking: {e}")
            return

        # Closure-safe callback factory
        def make_cbs(m: discord.Message, c: discord.abc.Messageable):
            async def edit_cb(new_content: str) -> None:
                await m.edit(content=new_content)
            async def send_cb(new_content: str) -> None:
                await c.send(new_content)
            return edit_cb, send_cb

        pending_tasks = []
        for item in target_items:
            url = str(item.get("url", ""))
            if not url or not is_valid_url(url):
                continue

            download_type = get_backup_item_download_type(item)
            job_id = str(item.get("job_id") or item.get("id") or item.get("jobId") or item.get("lzy_id") or "")

            try:
                sent_msg = await dm_channel.send(
                    f"{prefix} <{url}>\n*Connecting to LzyDownloader...*"
                )
                edit_msg_cb, send_msg_cb = make_cbs(sent_msg, dm_channel)

                job_registered = False
                if skip_enqueue:
                    if not job_id:
                        await edit_msg_cb("? Missing job_id for resumed download.")
                        continue
                    job_registered = await register_active_job(job_id, url)
                    if not job_registered:
                        print(f"Recovery job {job_id} is already tracked; skipping duplicate.")
                        continue

                pending_tasks.append(
                    (
                        url,
                        edit_msg_cb,
                        send_msg_cb,
                        download_type,
                        skip_enqueue,
                        job_id,
                        job_registered,
                    )
                )
            except Exception as e:
                print(f"Failed to start recovery task for {url}: {e}")

        # Register all restored jobs before launching the first task. The first
        # task may start LzyDownloader, which immediately emits events for the
        # entire restored queue.
        for (
            task_url,
            task_edit_msg,
            task_send_msg,
            task_download_type,
            task_skip_enqueue,
            task_job_id,
            task_job_registered,
        ) in pending_tasks:
            client.loop.create_task(
                run_download_job(
                    task_url,
                    task_edit_msg,
                    task_send_msg,
                    download_type=task_download_type,
                    skip_enqueue=task_skip_enqueue,
                    job_id=task_job_id,
                    job_registered=task_job_registered,
                )
            )


async def run_download_job(
    url: str,
    edit_msg: Callable[[str], Awaitable[None]],
    send_msg: Callable[[str], Awaitable[None]],
    download_type: str = "video",
    skip_enqueue: bool = False,
    job_id: Optional[str] = None,
    job_registered: bool = False
) -> None:
    """Enqueues a single download via the local API and polls until it finishes."""
    job_key = str(job_id) if job_registered and job_id else None
    if job_registered and not job_key:
        await edit_msg("? Missing job_id for resumed download.")
        return
    async with client.launch_lock:
        try:
            # Ensure the API is running before we queue
            await asyncio.to_thread(check_api_health)

        except Exception as e:
            if job_key:
                await unregister_active_job(job_key)
            await edit_msg(f"❌ {e}")
            return

    api_key = await asyncio.to_thread(get_lzy_api_key)
    if not api_key:
        if job_key:
            await unregister_active_job(job_key)
        await edit_msg("❌ Failed to read `api_token.txt`. The app may not have generated it.")
        return

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    proxies = {"http": "", "https": ""}
    
    if not skip_enqueue:
        payload = {
            "url": url, 
            "type": download_type,
            "download_type": download_type,
            "options": {
                "type": download_type
            }
        }
        
        if job_id:
            payload["job_id"] = job_id

        # Enqueue the download
        try:
            res = await asyncio.to_thread(
                requests.post,
                f"{BASE_URL}/enqueue",
                json=payload,
                headers=headers,
                timeout=30,
                proxies=proxies
            )
            if res.status_code != 200:
                raw_err = res.text
                if len(raw_err) > 500:
                    raw_err = raw_err[:497] + "..."
                safe_text = discord.utils.escape_markdown(raw_err).replace("|", "\\|")
                await edit_msg(f"❌ API rejected the download: HTTP {res.status_code}\n{safe_text}")
                return
                
            try:
                res_data = res.json()
                job_key = res_data.get("job_id") or res_data.get("id")
            except ValueError:
                job_key = None
                
            if not job_key:
                await edit_msg("❌ API response missing 'job_id'. Please update the C++ backend.")
                return
                
            job_key = str(job_key)
            
        except requests.exceptions.RequestException as e:
            await edit_msg(f"❌ Failed to reach the LzyDownloader Local API.\n`{e}`")
            return
    else:
        if not job_id:
            await edit_msg("❌ Missing job_id for resumed download.")
            return
        job_key = str(job_id)
        
    if not job_registered:
        await register_active_job(job_key, url)

    try:
        while job_key in client.active_jobs:
            current_data = client.active_jobs[job_key]
            
            if current_data["is_final"]:
                final_status = current_data["final_status"]
                display_title = current_data.get("title")
                if display_title:
                    if len(display_title) > 200:
                        display_title = display_title[:197] + "..."
                    display_title = discord.utils.escape_markdown(display_title).replace("|", "\\|")
                title_str = f"**{display_title}**\n<{url}>" if display_title else f"<{url}>"
                
                if final_status in {"completed", "complete", "finished"}:
                    final_msg = f"✅ **Download Complete:** {title_str}"
                else:
                    final_msg = f"❌ **Download {final_status.title()}:** {title_str}"
                    
                if len(final_msg) > 1950:
                    final_msg = final_msg[:1950] + "...\n[Message Truncated]"
                    
                try:
                    await edit_msg(final_msg)
                except Exception as e:
                    print(f"Failed to edit final message: {e}")
                break
                
            # Garbage collector timeout (12 hours without any webhook pushes)
            if time.time() - current_data["last_webhook_time"] > 43200:
                current_data["is_final"] = True
                current_data["final_status"] = "failed (timed out)"
                continue
                
            raw_status = str(current_data["status_text"])
            if current_data.get("queue_position") is not None and current_data.get("queue_position") > 0:
                raw_status = QUEUE_POSITION_REGEX.sub("", raw_status)
                raw_status += f" (Position: {current_data['queue_position']})"
            if len(raw_status) > 200:
                raw_status = raw_status[:197] + "..."
            status_text = discord.utils.escape_markdown(raw_status).replace("|", "\\|")
            progress_bar = create_progress_bar(current_data["progress"])
            
            display_title = current_data.get("title")
            if display_title:
                if len(display_title) > 200:
                    display_title = display_title[:197] + "..."
                display_title = discord.utils.escape_markdown(display_title).replace("|", "\\|")
            title_str = f"**{display_title}**" if display_title else f"<{url}>"
            
            current_message = (
                f"⏳ **Downloading:** {title_str}\n"
                f"**Status:** {status_text}\n"
                f"**Progress:** {progress_bar}\n"
            )
            if current_data["speed"]:
                current_message += f"**Speed:** {current_data['speed']}\n"
            if current_data["eta"]:
                current_message += f"**ETA:** {current_data['eta']}\n"
                
            if len(current_message) > 1950:
                current_message = current_message[:1950] + "...\n[Message Truncated]"
                
            if current_message != current_data["last_content"]:
                try:
                    await edit_msg(current_message)
                    current_data["last_content"] = current_message
                except Exception as e:
                    print(f"Failed to edit progress message: {e}")
                    
            await asyncio.sleep(1.5)
    finally:
        await unregister_active_job(job_key)


if __name__ == "__main__":
    if not TOKEN:
        print("❌ DISCORD_BOT_TOKEN is not set in the .env file. Exiting.")
        sys.exit(1)
        
    enforce_single_instance()
    client.run(TOKEN)
