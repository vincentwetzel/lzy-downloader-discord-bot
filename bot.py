import os
import asyncio
import time
import subprocess
import requests
import discord
from discord import app_commands
from dotenv import load_dotenv

# Load the Discord token from the .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
AUTHORIZED_USER_ID = os.getenv('AUTHORIZED_USER_ID')

# LzyDownloader Local API Settings
API_PORT = 8765
BASE_URL = f"http://127.0.0.1:{API_PORT}"

# IMPORTANT: Update this path to where your compiled LzyDownloader.exe is located!
LZY_EXECUTABLE_PATH = r"E:\coding_workspaces\CPP\LzyDownloader\build-debug\Debug\LzyDownloader.exe"

class LzyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Sync the slash commands to Discord when the bot starts
        await self.tree.sync()
        print("Bot is online and slash commands are synced!")

client = LzyBot()

def get_lzy_api_key():
    """Reads the auto-generated API key from LzyDownloader's AppData folder."""
    app_data = os.getenv('LOCALAPPDATA')
    key_path = os.path.join(app_data, 'LzyDownloader', 'api_token.txt')
    
    if not os.path.exists(key_path):
        return None
        
    with open(key_path, 'r', encoding='utf-8') as f:
        return f.read().strip()

def ensure_app_running():
    """Checks if the Local API is responding. If not, launches the app invisibly."""
    api_key = get_lzy_api_key()
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    
    try:
        # Try to ping the status endpoint
        requests.get(f"{BASE_URL}/status", headers=headers, timeout=1)
        return True
    except requests.RequestException:
        print("LzyDownloader is not running. Launching background API server...")
        app_dir = os.path.dirname(LZY_EXECUTABLE_PATH)
        # Launch the app invisibly and tell it to exit when the queue is done
        subprocess.Popen([LZY_EXECUTABLE_PATH, "--background", "--exit-after"], cwd=app_dir)
        time.sleep(2) # Give the C++ app a moment to bind the local port
        return True

def generate_progress_bar(percentage, length=15):
    """Generates a clean text-based progress bar."""
    if percentage < 0:
        return "[ Indeterminate / Processing ]"
    filled = int(length * (percentage / 100.0))
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percentage:.1f}%"

@client.tree.command(name="download", description="Send a media link to LzyDownloader on your PC.")
@app_commands.describe(url="The URL of the video or playlist to download")
async def download(interaction: discord.Interaction, url: str):
    if AUTHORIZED_USER_ID and str(interaction.user.id) != AUTHORIZED_USER_ID:
        await interaction.response.send_message("❌ **Unauthorized:** You do not have permission to use this bot.\n\nWant to run your own? Check out the project on GitHub: https://github.com/vincentwetzel/lzy-downloader", ephemeral=True)
        return

    await interaction.response.send_message(f"⏳ **Starting download:** {url}\n*Running in background...*", ephemeral=False)

    if not os.path.exists(LZY_EXECUTABLE_PATH):
        await interaction.edit_original_response(content=f"❌ **Error:** Executable not found at `{LZY_EXECUTABLE_PATH}`")
        return

    # 1. Ensure C++ App is running and get API Key
    try:
        await asyncio.to_thread(ensure_app_running)
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ **Failed to start LzyDownloader:** {str(e)}")
        return
    
    api_key = get_lzy_api_key()
    if not api_key:
        await interaction.edit_original_response(content="❌ **Error:** Could not find LzyDownloader API Key on the host PC.")
        return

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # 2. Enqueue the URL securely to the C++ App via JSON API
    try:
        enqueue_res = await asyncio.to_thread(requests.post, f"{BASE_URL}/enqueue", headers=headers, json={"url": url}, timeout=5)
        if enqueue_res.status_code != 200:
            await interaction.edit_original_response(content=f"❌ **Failed to enqueue:** {enqueue_res.text}")
            return
    except Exception as e:
        await interaction.edit_original_response(content=f"❌ **Connection Error:** {str(e)}")
        return

    # 3. Enter the Progress Polling Loop
    completed = False
    last_msg = ""
    fail_count = 0
    
    while not completed:
        await asyncio.sleep(4) # Throttle updates to obey Discord rate limits
        
        try:
            status_res = await asyncio.to_thread(requests.get, f"{BASE_URL}/status", headers=headers, timeout=2)
            if status_res.status_code == 200:
                fail_count = 0
                jobs = status_res.json().get("jobs", [])
                my_job = next((j for j in jobs if j.get("url") == url), None)
                
                if my_job:
                    status_str = my_job.get("status", "Downloading...")
                    title = my_job.get("title", url)
                    prog_bar = generate_progress_bar(my_job.get("progress", -1))
                    speed, eta = my_job.get("speed", "N/A"), my_job.get("eta", "N/A")
                    
                    if "Complete" in status_str:
                        msg, completed = f"🎉 **Download Complete!**\n**{title}**\nStatus: {status_str}", True
                    elif any(err in status_str for err in ["Error", "Failed", "Stopped"]):
                        msg, completed = f"❌ **Download Failed!**\n**{title}**\nError: {status_str}", True
                    else:
                        msg = f"📥 **Downloading:** {title}\n{prog_bar} | Speed: {speed} | ETA: {eta}\n*Status: {status_str}*"
                        
                    try:
                        if msg != last_msg:
                            await interaction.edit_original_response(content=msg)
                            last_msg = msg
                    except Exception:
                        pass
                else:
                    # Job finished and was cleared from the API queue
                    try:
                        await interaction.edit_original_response(content=f"🎉 **Download Complete!**\n**{url}**")
                    except Exception:
                        pass
                    completed = True
        except Exception:
            fail_count += 1
            if fail_count >= 3:
                # App likely exited automatically (--exit-after), meaning the queue is done
                try:
                    await interaction.edit_original_response(content=f"🎉 **Download Complete!**\n**{url}**")
                except Exception:
                    pass
                completed = True

if __name__ == '__main__':
    if not TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not found in .env file!")
    else:
        print("Starting LzyDownloader Discord Bridge...")
        client.run(TOKEN)
