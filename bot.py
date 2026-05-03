import os
import asyncio
import json
import socket
import sys
import time
import subprocess
import requests
import discord
from discord import app_commands
from dotenv import load_dotenv
from urllib.parse import urlparse
from typing import Optional, Callable, Awaitable, Any, Dict, List, Set, Tuple

# Load the Discord token from the .env file located in the script's directory
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path=env_path)
TOKEN: Optional[str] = os.getenv('DISCORD_BOT_TOKEN')
AUTHORIZED_USER_ID: Optional[str] = os.getenv('AUTHORIZED_USER_ID')

# LzyDownloader Local API Settings
API_PORT: int = 8765
BASE_URL: str = f"http://127.0.0.1:{API_PORT}"
BACKUP_ARCHIVE_RETENTION: int = 5

# Load from .env
LZY_EXECUTABLE_PATH: Optional[str] = os.getenv('LZY_EXECUTABLE_PATH')

# Global reference to prevent the socket from being garbage collected
_lock_socket: Optional[socket.socket] = None
_launch_lock: asyncio.Lock = asyncio.Lock()
_active_jobs: int = 0
_jobs_lock: asyncio.Lock = asyncio.Lock()
_startup_resume_started: bool = False
_recovery_lock: asyncio.Lock = asyncio.Lock()

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

def is_valid_url(url: str) -> bool:
    """Validates that a string is a properly formatted HTTP/HTTPS URL."""
    try:
        result = urlparse(url)
        return result.scheme in ('http', 'https') and bool(result.netloc)
    except Exception:
        return False

def create_progress_bar(progress: float, length: int = 20) -> str:
    """Generates an ASCII progress bar for Discord messages."""
    try:
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
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        # Sync the slash commands to Discord when the bot starts
        await self.tree.sync()
        print("Bot is online and slash commands are synced!")

    async def on_ready(self) -> None:
        self.loop.create_task(resume_backed_up_downloads_on_startup())
        
        if AUTHORIZED_USER_ID:
            try:
                user = await self.fetch_user(int(AUTHORIZED_USER_ID))
                await user.send("🟢 **LzyDownloader Discord Bridge is now online!**")

                # Check for missed DMs sent while the bot was offline
                dm_channel = await user.create_dm()
                messages = [m async for m in dm_channel.history(limit=20)]

                missed_msgs = []
                for i, msg in enumerate(messages):
                    if msg.author.id == int(AUTHORIZED_USER_ID):
                        content = msg.content.strip()
                        if is_valid_url(content):
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

    async def close(self) -> None:
        if AUTHORIZED_USER_ID:
            try:
                user = await self.fetch_user(int(AUTHORIZED_USER_ID))
                await user.send("🔴 **LzyDownloader Discord Bridge is now offline.**")
            except Exception as e:
                print(f"Failed to send shutdown DM: {e}")
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
        await interaction.response.send_message("? Unauthorized.", ephemeral=True)
        return

    removed_count, kept_count, archive_path = clear_failed_backup_items()
    if removed_count == 0:
        await interaction.response.send_message(
            "No failed or stopped recovery jobs were found in `downloads_backup.json`.",
            ephemeral=True
        )
        return

    message = (
        f"Cleared {removed_count} failed/stopped recovery job(s) from "
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
        await interaction.response.send_message("? Unauthorized.", ephemeral=True)
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
    """Reads the auto-generated API key from LzyDownloader's AppData folder."""
    key_path = os.path.join(get_lzy_server_data_dir(), 'api_token.txt')
    
    if not os.path.exists(key_path):
        return None
        
    with open(key_path, 'r', encoding='utf-8') as f:
        return f.read().strip()


def get_lzy_server_data_dir() -> str:
    """Returns the LzyDownloader data directory used by --server launches."""
    app_data = os.getenv('LOCALAPPDATA', '')
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
        if (
            str(item.get("url")) == url
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
        status in {"stopped", "failed"}
        or bool(options.get("is_failed"))
        or bool(options.get("is_stopped"))
    )


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
    kept_items = [
        item for item in items
        if item.get("url") and not should_retry_backup_item(item)
    ]
    if not failed_items:
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
            return len(failed_items), len(kept_items), archive_path

    return len(failed_items), len(kept_items), archive_path


def check_api_health() -> None:
    """Checks if the Local API is responding. If not, launches the app and waits for it."""
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
    process = subprocess.Popen(
        [LZY_EXECUTABLE_PATH, "--server", "--exit-after"], 
        cwd=app_dir, 
        creationflags=creation_flags
    )

    # Now, poll for it to become ready
    last_error = "Timed out."
    for _ in range(20):  # Poll for up to 20 seconds
        time.sleep(1)
        
        if process.poll() is not None:
            raise RuntimeError(
                f"**LzyDownloader crashed or closed immediately.** Exit code: {process.returncode}.\n"
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


async def resume_backed_up_downloads_on_startup(
    force: bool = False,
    user: Any = None
) -> None:
    """Resumes tracking of backed up downloads or retries failed ones."""
    global _startup_resume_started

    async with _recovery_lock:
        if not force and _startup_resume_started:
            return
        if not force:
            _startup_resume_started = True

        items = await asyncio.to_thread(load_download_backup_items)
        if not items:
            return

        if force:
            retry_items = [item for item in items if should_retry_backup_item(item)]
            keep_items = [
                item for item in items
                if item.get("url") and not should_retry_backup_item(item)
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
            target_items = [item for item in items if not should_retry_backup_item(item)]
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

        for item in target_items:
            url = str(item.get("url", ""))
            if not url or not is_valid_url(url):
                continue

            download_type = get_backup_item_download_type(item)

            try:
                sent_msg = await dm_channel.send(
                    f"{prefix} <{url}>\n*Connecting to LzyDownloader...*"
                )
                edit_msg_cb, send_msg_cb = make_cbs(sent_msg, dm_channel)

                client.loop.create_task(
                    run_download_job(
                        url,
                        edit_msg_cb,
                        send_msg_cb,
                        download_type=download_type,
                        skip_enqueue=skip_enqueue
                    )
                )
            except Exception as e:
                print(f"Failed to start recovery task for {url}: {e}")


async def run_download_job(
    url: str,
    edit_msg: Callable[[str], Awaitable[None]],
    send_msg: Callable[[str], Awaitable[None]],
    download_type: str = "video",
    skip_enqueue: bool = False
) -> None:
    """Enqueues a single download via the local API and polls until it finishes."""
    global _active_jobs

    async with _launch_lock:
        try:
            # Ensure the API is running before we queue
            await asyncio.to_thread(check_api_health)
        except Exception as e:
            await edit_msg(f"❌ {e}")
            return

    api_key = await asyncio.to_thread(get_lzy_api_key)
    if not api_key:
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

        # Enqueue the download
        try:
            res = await asyncio.to_thread(
                requests.post,
                f"{BASE_URL}/enqueue",
                json=payload,
                headers=headers,
                timeout=5,
                proxies=proxies
            )
            if res.status_code != 200:
                await edit_msg(f"❌ API rejected the download: HTTP {res.status_code}\n{res.text}")
                return
        except requests.exceptions.RequestException as e:
            await edit_msg(f"❌ Failed to reach the LzyDownloader Local API.\n`{e}`")
            return

    async with _jobs_lock:
        _active_jobs += 1

    last_status_message = ""
    poll_interval = 1.5

    try:
        while True:
            await asyncio.sleep(poll_interval)
            try:
                res = await asyncio.to_thread(
                    requests.get,
                    f"{BASE_URL}/status",
                    headers=headers,
                    timeout=5,
                    proxies=proxies
                )
            except requests.exceptions.RequestException:
                # The app might have closed successfully (e.g., 'exit after' is enabled). Check the backup file.
                backup_item = await asyncio.to_thread(find_backup_item, url, download_type)
                if backup_item:
                    backup_status = str(backup_item.get("status", "")).lower()
                    if backup_status == "completed":
                        await edit_msg(f"✅ **Download Complete:** <{url}>")
                    elif backup_status in {"failed", "stopped"}:
                        await edit_msg(f"❌ **Download {backup_status.title()}:** <{url}>")
                    else:
                        await edit_msg(f"❌ Connection to LzyDownloader lost while processing <{url}>.")
                else:
                    await edit_msg(f"✅ **Download Finished:** <{url}>")
                break

            if res.status_code != 200:
                await edit_msg(f"❌ API polling failed: HTTP {res.status_code}")
                break

            data = res.json()
            jobs = data.get("jobs", [])

            my_job = None
            for job in jobs:
                if str(job.get("url")) == url and get_backup_item_download_type(job) == download_type:
                    my_job = job
                    break

            if not my_job:
                # If it's not in the active list, check the backup queue to see if it finished or failed
                backup_item = await asyncio.to_thread(find_backup_item, url, download_type)
                if backup_item:
                    backup_status = str(backup_item.get("status", "")).lower()
                    if backup_status == "completed":
                        await edit_msg(f"✅ **Download Complete:** <{url}>")
                    elif backup_status in {"failed", "stopped"}:
                        await edit_msg(f"❌ **Download {backup_status.title()}:** <{url}>")
                    else:
                        await edit_msg(f"⚠️ Download vanished from API but is in backup as `{backup_status}`: <{url}>")
                else:
                    await edit_msg(f"✅ **Download Finished:** <{url}>")
                break

            progress = my_job.get("progress", 0.0)
            status_text = my_job.get("status", "Processing")
            speed = my_job.get("speed", "")
            eta = my_job.get("eta", "")
            
            # Escape markdown formatting if present in the status
            status_text = str(status_text).replace("*", "\\*").replace("_", "\\_").replace("~", "\\~")

            progress_bar = create_progress_bar(progress)

            current_message = (
                f"⏳ **Downloading:** <{url}>\n"
                f"**Status:** {status_text}\n"
                f"**Progress:** {progress_bar}\n"
            )
            if speed:
                current_message += f"**Speed:** {speed}\n"
            if eta:
                current_message += f"**ETA:** {eta}\n"

            if current_message != last_status_message:
                try:
                    await edit_msg(current_message)
                    last_status_message = current_message
                except discord.errors.HTTPException:
                    pass

    finally:
        async with _jobs_lock:
            _active_jobs = max(0, _active_jobs - 1)


if __name__ == "__main__":
    if not TOKEN:
        print("❌ DISCORD_BOT_TOKEN is not set in the .env file. Exiting.")
        sys.exit(1)
        
    enforce_single_instance()
    client.run(TOKEN)