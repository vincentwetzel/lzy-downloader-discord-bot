import os
import asyncio
import socket
import sys
import time
import subprocess
import requests
import discord
from discord import app_commands
from dotenv import load_dotenv
from urllib.parse import urlparse
from typing import Optional, Callable, Awaitable

# Load the Discord token from the .env file located in the script's directory
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path=env_path)
TOKEN: Optional[str] = os.getenv('DISCORD_BOT_TOKEN')
AUTHORIZED_USER_ID: Optional[str] = os.getenv('AUTHORIZED_USER_ID')

# LzyDownloader Local API Settings
API_PORT: int = 8765
BASE_URL: str = f"http://127.0.0.1:{API_PORT}"

# Load from .env
LZY_EXECUTABLE_PATH: Optional[str] = os.getenv('LZY_EXECUTABLE_PATH')

# Global reference to prevent the socket from being garbage collected
_lock_socket: Optional[socket.socket] = None
_launch_lock: asyncio.Lock = asyncio.Lock()
_active_jobs: int = 0
_jobs_lock: asyncio.Lock = asyncio.Lock()

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

def get_lzy_api_key() -> Optional[str]:
    """Reads the auto-generated API key from LzyDownloader's AppData folder."""
    app_data = os.getenv('LOCALAPPDATA', '')
    key_path = os.path.join(app_data, 'LzyDownloader', 'Server', 'api_token.txt')
    
    if not os.path.exists(key_path):
        return None
        
    with open(key_path, 'r', encoding='utf-8') as f:
        return f.read().strip()

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
    app_data = os.getenv('LOCALAPPDATA', '')
    key_path = os.path.join(app_data, 'LzyDownloader', 'Server', 'api_token.txt')
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
                print("LzyDownloader API is now online.")
                return  # Success!
            last_error = f"API responded with HTTP {res.status_code}."
        except requests.exceptions.RequestException:
            last_error = "Connection refused. Waiting for server to start..."
            continue

    raise RuntimeError(f"**Failed to start LzyDownloader.**\nLast known issue: {last_error}")

async def is_api_still_running() -> bool:
    """Checks if the Local API is responding without trying to launch it."""
    try:
        api_key = await asyncio.to_thread(get_lzy_api_key)
        if not api_key:
            return False

        headers = {"Authorization": f"Bearer {api_key}"}
        proxies = {"http": "", "https": ""}
        
        res = await asyncio.to_thread(
            requests.get,
            f"{BASE_URL}/status", headers=headers, timeout=1, proxies=proxies
        )
        return res.status_code == 200
    except requests.exceptions.RequestException:
        return False
    except Exception:
        return False

def generate_progress_bar(percentage: float, length: int = 15) -> str:
    """Generates a clean text-based progress bar."""
    if percentage < 0:
        return "[ Indeterminate / Processing ]"
    filled = int(length * (percentage / 100.0))
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percentage:.1f}%"

async def run_download_job(
    url: str, 
    edit_callback: Callable[[str], Awaitable[None]], 
    send_callback: Callable[[str], Awaitable[None]], 
    download_type: str = "video"
) -> None:
    """Core logic to communicate with the local API and handle status polling."""
    # 1. Check if the C++ App API is healthy and authorized
    try:
        async with _launch_lock:
            await asyncio.to_thread(check_api_health)
    except Exception as e:
        await edit_callback(f"❌ {str(e)}")
        return

    api_key = get_lzy_api_key()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # 2. Enqueue the URL securely to the C++ App via JSON API
    try:
        enqueue_res = await asyncio.to_thread(
            requests.post, 
            f"{BASE_URL}/enqueue", 
            headers=headers, 
            json={"url": url, "type": download_type}, 
            timeout=5, 
            proxies={"http": "", "https": ""}
        )
        if enqueue_res.status_code != 200:
            await edit_callback(f"❌ **Failed to enqueue:** {enqueue_res.text}")
            return
    except Exception as e:
        await edit_callback(f"❌ **Connection Error:** {str(e)}")
        return

    # 3. Enter the Progress Polling Loop
    completed = False
    last_msg = ""
    fail_count = 0
    last_title = url
    is_success = False
    
    while not completed:
        await asyncio.sleep(4)  # Throttle updates to obey Discord rate limits
        
        try:
            status_res = await asyncio.to_thread(
                requests.get, 
                f"{BASE_URL}/status", 
                headers=headers, 
                timeout=5, 
                proxies={"http": "", "https": ""}
            )
            if status_res.status_code == 200:
                fail_count = 0
                jobs = status_res.json().get("jobs", [])
                my_job = next((j for j in jobs if j.get("url") == url), None)
                
                if my_job:
                    status_str = my_job.get("status", "Downloading...")
                    title = my_job.get("title", url)
                    last_title = title
                    prog_bar = generate_progress_bar(my_job.get("progress", -1))
                    speed, eta = my_job.get("speed", "N/A"), my_job.get("eta", "N/A")
                    
                    if "Complete" in status_str:
                        msg = f"🎉 **Download Complete!**\n**{title}**\nStatus: {status_str}"
                        completed = True
                        is_success = True
                    elif any(err in status_str for err in ["Error", "Failed", "Stopped"]):
                        msg = f"❌ **Download Failed!**\n**{title}**\nError: {status_str}"
                        completed = True
                        is_success = False
                    else:
                        msg = (
                            f"📥 **Downloading:** {title}\n{prog_bar} | "
                            f"Speed: {speed} | ETA: {eta}\n*Status: {status_str}*"
                        )
                        
                    try:
                        if msg != last_msg:
                            await edit_callback(msg)
                            last_msg = msg
                    except Exception:
                        pass
                else:
                    # Job finished and was cleared from the API queue
                    try:
                        await edit_callback(f"🎉 **Download Complete!**\n**{last_title}**")
                    except Exception:
                        pass
                    completed = True
                    is_success = True
        except Exception:
            fail_count += 1
            if fail_count >= 3:
                # App likely exited automatically (--exit-after), meaning the queue is done
                try:
                    await edit_callback(f"🎉 **Download Complete!**\n**{last_title}**")
                except Exception:
                    pass
                completed = True
                is_success = True

    if is_success:
        try:
            await send_callback(f"✅ **Finished downloading:** {last_title}")
        except Exception:
            pass

if __name__ == '__main__':
    enforce_single_instance()

    if not TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not found in .env file!")
    elif not AUTHORIZED_USER_ID:
        print(
            "ERROR: AUTHORIZED_USER_ID not found in .env file! "
            "Exiting to prevent unauthorized access to your machine."
        )
        sys.exit(1)
    elif not LZY_EXECUTABLE_PATH:
        print(
            "ERROR: LZY_EXECUTABLE_PATH not found in .env file! "
            "Please add it to configure the path to the LzyDownloader executable."
        )
        sys.exit(1)
    else:
        print("Starting LzyDownloader Discord Bridge...")
        client.run(TOKEN)
