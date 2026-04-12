import os
import sys
import time
import aiosqlite
import discord
import asyncio
import platform
import aiohttp
import shutil
import stat
import zipfile
from datetime import datetime, timezone
from discord.ext import commands, tasks
from openai import AsyncOpenAI
from dotenv import load_dotenv


def is_admin():
    async def predicate(ctx):
        if ctx.author.id == ctx.bot.admin_user_id:
            return True
        await ctx.send("You do not have permission to use this command.")
        return False
    return commands.check(predicate)


class BotCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="p", aliases=["ping"], help="Checks latency. (;p)")
    async def ping(self, ctx):
        latency_ms = round(self.bot.latency * 1000)
        await ctx.send(f"Pong! Latency: {latency_ms}ms")

    @commands.command(name="r", aliases=["reset", "wipe"], help="Clears memory for this channel. (;r)")
    async def reset_memory(self, ctx):
        await self.bot._clear_history(ctx.channel.id)
        channel_name = "DM" if isinstance(ctx.channel, discord.DMChannel) else f"#{ctx.channel.name}"
        await ctx.send(f"Memory wiped for {channel_name}. Starting fresh.")

    @commands.command(name="s", aliases=["stats", "st"], help="Shows bot stats. (;s)")
    async def show_stats(self, ctx):
        uptime = int(time.time() - self.bot.bot_stats["start_time"])
        mins, secs = divmod(uptime, 60)
        hours, mins = divmod(mins, 60)

        history = await self.bot._get_history(ctx.channel.id)

        embed = discord.Embed(title="Bot Statistics", color=discord.Color.blue())
        embed.add_field(name="Uptime", value=f"{hours}h {mins}m {secs}s", inline=False)
        embed.add_field(name="Messages Seen", value=str(self.bot.bot_stats["messages_seen"]), inline=True)
        embed.add_field(name="Processed", value=str(self.bot.bot_stats["messages_processed"]), inline=True)
        embed.add_field(name="Errors", value=str(self.bot.bot_stats["errors"]), inline=True)
        embed.add_field(name="Current Channel Memory", value=f"{len(history)} / {self.bot.bot_config['max_history']} msgs", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="c", aliases=["config", "cfg"], help="Displays current bot parameters. (;c)")
    async def show_config(self, ctx):
        embed = discord.Embed(title="Bot Configuration", color=discord.Color.green())
        embed.add_field(name="Target User Persona", value=self.bot.target_user, inline=True)
        embed.add_field(name="Admin User", value=self.bot.admin_user_id or "None Set", inline=True)
        embed.add_field(name="Max History (Memory)", value=str(self.bot.bot_config["max_history"]), inline=True)
        embed.add_field(name="Track Non-Mentions", value=str(self.bot.bot_config["track_non_mentions"]), inline=True)
        embed.add_field(name="Bot Enabled", value=str(self.bot.bot_config["enabled"]), inline=True)
        embed.add_field(name="Any Message Mode", value=str(self.bot.bot_config["reply_any_message"]), inline=True)
        embed.add_field(name="Queue Expiration", value=f"{self.bot.bot_config['queue_expiration']}s", inline=True)
        embed.add_field(name="Autoupdate", value=str(self.bot.bot_config["autoupdate"]), inline=True)

        channel_name = "None (Any)"
        allowed_id = self.bot.bot_config["allowed_channel_id"]
        if allowed_id:
            try:
                channel = self.bot.get_channel(allowed_id) or await self.bot.fetch_channel(allowed_id)
                channel_name = f"#{channel.name}" if hasattr(channel, 'name') else str(allowed_id)
            except (discord.NotFound, discord.HTTPException):
                channel_name = f"Unknown Channel ID ({allowed_id})"

        embed.add_field(name="Restricted Channel", value=channel_name, inline=True)
        embed.add_field(name="LLM Endpoint", value=self.bot.base_url, inline=False)

        prompt_text = self.bot.bot_config.get("system_prompt", "None")
        if len(prompt_text) > 1000:
            prompt_text = prompt_text[:1000] + "... [Truncated]"
        embed.add_field(name="Current System Prompt", value=f"```\n{prompt_text}\n```", inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="sp", aliases=["set_prompt", "prompt"], help="[Admin] Set system prompt. (;sp <prompt>)")
    @is_admin()
    async def set_prompt(self, ctx, *, new_prompt: str):
        await self.bot._update_config("system_prompt", new_prompt)
        await ctx.send("System prompt updated successfully.")

    @commands.command(name="tb", aliases=["toggle_bot", "on", "off"], help="[Admin] Toggle replies. (;tb)")
    @is_admin()
    async def toggle_bot(self, ctx):
        new_state = not self.bot.bot_config["enabled"]
        await self.bot._update_config("enabled", new_state)
        await self.bot.update_bot_presence()
        state_str = "ON" if new_state else "OFF"
        await ctx.send(f"Bot answering is now **{state_str}**.")

    @commands.command(name="tt", aliases=["toggle_tracking", "track"], help="[Admin] Toggle non-mention tracking. (;tt)")
    @is_admin()
    async def toggle_tracking(self, ctx):
        new_state = not self.bot.bot_config["track_non_mentions"]
        await self.bot._update_config("track_non_mentions", new_state)
        state_str = "ON" if new_state else "OFF"
        await ctx.send(f"Tracking of non-mention messages is now **{state_str}**.")

    @commands.command(name="ta", aliases=["toggle_anymessage", "any"], help="[Admin] Toggle 'any message' mode. (;ta)")
    @is_admin()
    async def toggle_anymessage(self, ctx):
        new_state = not self.bot.bot_config["reply_any_message"]
        await self.bot._update_config("reply_any_message", new_state)
        state_str = "ON" if new_state else "OFF"
        await ctx.send(f"Any message mode is now **{state_str}**.")

    @commands.command(name="au", aliases=["autoupdate"], help="[Admin] Toggle automatic background updates. (;au)")
    @is_admin()
    async def toggle_autoupdate(self, ctx):
        new_state = not self.bot.bot_config["autoupdate"]
        await self.bot._update_config("autoupdate", new_state)

        if new_state and not self.bot.github_repo:
            await ctx.send("⚠️ WARNING: `GITHUB_REPO` is not set in your `.env` file. Background autoupdates will not function.")

        state_str = "ON" if new_state else "OFF"
        await ctx.send(f"Background autoupdate is now **{state_str}**.")

    @commands.command(name="sc", aliases=["set_channel", "chan"], help="[Admin] Restrict to channel. 'clear' to undo. (;sc)")
    @is_admin()
    async def set_channel(self, ctx, arg: str = None):
        if arg and arg.lower() == "clear":
            await self.bot._update_config("allowed_channel_id", None)
            await ctx.send("Channel restriction removed. The bot can now reply in any channel.")
        else:
            await self.bot._update_config("allowed_channel_id", ctx.channel.id)
            channel_name = "DM" if isinstance(ctx.channel, discord.DMChannel) else f"#{ctx.channel.name}"
            await ctx.send(f"Bot is now restricted to channel: {channel_name}")

        await self.bot.update_bot_presence()

    @commands.command(name="sh", aliases=["set_history", "hist"], help="[Admin] Set max history length. (;sh <num>)")
    @is_admin()
    async def set_history(self, ctx, length: int):
        if length < 1:
            await ctx.send("History length must be at least 1.")
            return
        await self.bot._update_config("max_history", length)
        await ctx.send(f"Max history set to {length} messages.")

    @commands.group(name="whitelist", help="[Admin] Manage DM whitelist. (;whitelist <add|remove|list>)")
    @is_admin()
    async def whitelist(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Usage: `;whitelist <add|remove|list> [user_id]`")

    @whitelist.command(name="add")
    @is_admin()
    async def whitelist_add(self, ctx, user_id: int):
        await self.bot._add_whitelist(user_id)
        await ctx.send(f"User ID `{user_id}` has been added to the DM whitelist.")

    @whitelist.command(name="remove")
    @is_admin()
    async def whitelist_remove(self, ctx, user_id: int):
        await self.bot._remove_whitelist(user_id)
        await ctx.send(f"User ID `{user_id}` has been removed from the DM whitelist.")

    @whitelist.command(name="list")
    @is_admin()
    async def whitelist_list(self, ctx):
        wl = await self.bot._get_whitelist()
        if not wl:
            await ctx.send("The DM whitelist is currently empty.")
            return

        wl_str = "\n".join([f"- `{uid}`" for uid in wl])
        await ctx.send(f"**DM Whitelisted Users:**\n{wl_str}")

    @commands.command(name="se", aliases=["set_expiration", "expire"], help="[Admin] Set queue expiration time in seconds. (;se <num>)")
    @is_admin()
    async def set_expiration(self, ctx, seconds: int):
        if seconds < 0:
            await ctx.send("Expiration must be at least 0 seconds.")
            return
        await self.bot._update_config("queue_expiration", seconds)
        await ctx.send(f"Queue expiration set to {seconds} seconds.")

    @commands.command(name="rc", aliases=["reset_config"], help="[Admin] Reset configuration to default values. (;rc)")
    @is_admin()
    async def reset_config(self, ctx):
        await self.bot._reset_to_defaults()
        await self.bot.update_bot_presence()
        await ctx.send("Bot configuration has been restored to default values.")

    @commands.command(name="up", aliases=["update"], help="[Admin] Force update and restart bot script. (;up)")
    @is_admin()
    async def update_bot(self, ctx):
        try:
            await ctx.message.add_reaction('🔄')
        except discord.HTTPException:
            pass
        await self.bot.perform_update(ctx.channel)

    @commands.command(name="rs", aliases=["restart"], help="[Admin] Restarts bot script safely. (;rs)")
    @is_admin()
    async def restart(self, ctx):
        if self.bot.shutting_down:
            return

        self.bot.shutting_down = True
        try:
            await ctx.message.add_reaction('🔄')
        except discord.HTTPException:
            pass
        await ctx.send("Waiting for current generation to finish before restarting...")

        async with self.bot.global_llm_lock:
            await ctx.send("Restarting bot script...")
            await self.bot._update_config("restart_channel_id", ctx.channel.id)
            await self.bot.close()

            env = os.environ.copy()
            env.pop('_MEIPASS2', None)
            env.pop('_MEIPASS', None)

            if getattr(sys, 'frozen', False):
                os.execve(sys.executable, sys.argv, env)
            else:
                os.execve(sys.executable, [sys.executable] + sys.argv, env)

    @commands.command(name="sd", aliases=["shutdown", "kill"], help="[Admin] Shuts down bot safely. (;sd)")
    @is_admin()
    async def shutdown(self, ctx):
        if self.bot.shutting_down:
            return

        self.bot.shutting_down = True
        try:
            await ctx.message.add_reaction('🛑')
        except discord.HTTPException:
            pass
        await ctx.send("Waiting for current queue to finish before shutting down...")

        async with self.bot.global_llm_lock:
            await ctx.send("Shutting down...")
            await self.bot.close()
            sys.exit(0)


class DiscordLLMBot(commands.Bot):
    def __init__(self):
        load_dotenv()

        self.target_user = os.getenv("TARGET_USER")
        self.bot_token = os.getenv("DISCORD_BOT_TOKEN")
        self.base_url = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
        self.api_key = os.getenv("LM_STUDIO_API_KEY", "lm-studio")
        self.admin_user_id = int(os.getenv("ADMIN_USER_ID", 0))
        self.github_repo = os.getenv("GITHUB_REPO")
        self.current_version = os.getenv("CURRENT_VERSION", "v1.0.0")

        self.current_status_hash = None
        self.shutting_down = False

        if not self.bot_token or not self.target_user:
            print("Error: DISCORD_BOT_TOKEN and TARGET_USER must be set in your .env file.")
            sys.exit(1)

        self.system_prompt_default = f"You are {self.target_user} in a Discord chat."

        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(command_prefix=";", intents=intents)

        self.client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
        self.global_llm_lock = asyncio.Lock()
        self.db_path = "bot_data.db"

        self.bot_config = {}
        self.bot_stats = {
            "start_time": time.time(),
            "messages_seen": 0,
            "messages_processed": 0,
            "errors": 0
        }

    async def setup_hook(self):
        await self._init_db()
        await self._load_config()
        await self.add_cog(BotCommands(self))
        self.autoupdate_check.start()

    async def _init_db(self):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute('''CREATE TABLE IF NOT EXISTS config
                            (key TEXT PRIMARY KEY, value TEXT)''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS history
                            (channel_id INTEGER, role TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, message_id INTEGER)''')

            try:
                await conn.execute('ALTER TABLE history ADD COLUMN message_id INTEGER')
            except aiosqlite.OperationalError:
                pass

            await conn.execute('''CREATE TABLE IF NOT EXISTS dm_whitelist
                            (user_id INTEGER PRIMARY KEY)''')
            await conn.commit()

    async def _load_config(self):
        defaults = {
            "max_history": "15",
            "track_non_mentions": "False",
            "enabled": "False",
            "reply_any_message": "False",
            "allowed_channel_id": "None",
            "system_prompt": self.system_prompt_default,
            "restart_channel_id": "None",
            "queue_expiration": "60",
            "autoupdate": "False"
        }

        async with aiosqlite.connect(self.db_path) as conn:
            for key, default in defaults.items():
                async with conn.execute("SELECT value FROM config WHERE key = ?", (key,)) as cursor:
                    row = await cursor.fetchone()
                    val_str = row[0] if row else default

                    if not row:
                        await conn.execute("INSERT INTO config (key, value) VALUES (?, ?)", (key, default))

                if val_str in ("True", "False"):
                    self.bot_config[key] = (val_str == "True")
                elif key == "max_history":
                    self.bot_config[key] = int(val_str)
                elif key in ("allowed_channel_id", "restart_channel_id"):
                    self.bot_config[key] = int(val_str) if val_str != "None" else None
                elif key == "queue_expiration":
                    self.bot_config[key] = int(val_str)
                else:
                    self.bot_config[key] = val_str
            await conn.commit()

    async def _update_config(self, key, value):
        self.bot_config[key] = value
        val_str = str(value) if value is not None else "None"
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("UPDATE config SET value = ? WHERE key = ?", (val_str, key))
            await conn.commit()

    async def _reset_to_defaults(self):
        defaults = {
            "max_history": "15",
            "track_non_mentions": "False",
            "enabled": "False",
            "reply_any_message": "False",
            "allowed_channel_id": "None",
            "system_prompt": self.system_prompt_default,
            "restart_channel_id": "None",
            "queue_expiration": "60",
            "autoupdate": "False"
        }
        async with aiosqlite.connect(self.db_path) as conn:
            for key, default in defaults.items():
                await conn.execute("UPDATE config SET value = ? WHERE key = ?", (default, key))

                if default in ("True", "False"):
                    self.bot_config[key] = (default == "True")
                elif key == "max_history":
                    self.bot_config[key] = int(default)
                elif key in ("allowed_channel_id", "restart_channel_id"):
                    self.bot_config[key] = None
                else:
                    self.bot_config[key] = default
            await conn.commit()

    async def _get_history(self, channel_id):
        max_h = self.bot_config["max_history"]
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("""SELECT role, content FROM (
                                SELECT role, content, timestamp FROM history
                                WHERE channel_id = ?
                                ORDER BY timestamp DESC LIMIT ?
                              ) ORDER BY timestamp ASC""", (channel_id, max_h)) as cursor:
                return [{"role": row[0], "content": row[1]} for row in await cursor.fetchall()]

    async def _add_to_history(self, channel_id, role, content, message_id=None):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT INTO history (channel_id, role, content, message_id) VALUES (?, ?, ?, ?)",
                               (channel_id, role, content, message_id))
            await conn.commit()

    async def _pop_last_history(self, channel_id):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM history WHERE rowid = (SELECT MAX(rowid) FROM history WHERE channel_id = ?)", (channel_id,))
            await conn.commit()

    async def _clear_history(self, channel_id):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM history WHERE channel_id = ?", (channel_id,))
            await conn.commit()

    async def _is_whitelisted(self, user_id):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT 1 FROM dm_whitelist WHERE user_id = ?", (user_id,)) as cursor:
                return await cursor.fetchone() is not None

    async def _add_whitelist(self, user_id):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR IGNORE INTO dm_whitelist (user_id) VALUES (?)", (user_id,))
            await conn.commit()

    async def _remove_whitelist(self, user_id):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM dm_whitelist WHERE user_id = ?", (user_id,))
            await conn.commit()

    async def _get_whitelist(self):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT user_id FROM dm_whitelist") as cursor:
                return [row[0] for row in await cursor.fetchall()]

    @tasks.loop(hours=6)
    async def autoupdate_check(self):
        if not self.bot_config.get("autoupdate", False):
            return

        update_needed = False
        if getattr(sys, 'frozen', False):
            if self.github_repo:
                async with aiohttp.ClientSession() as session:
                    url = f"https://api.github.com/repos/{self.github_repo}/releases/latest"
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            latest_tag = data.get("tag_name", "")
                            if latest_tag and latest_tag != self.current_version:
                                update_needed = True
        else:
            process = await asyncio.create_subprocess_shell(
                "git fetch && git status -sb",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await process.communicate()
            if b"behind" in stdout:
                update_needed = True

        if update_needed:
            restart_channel = self.bot_config.get("restart_channel_id")
            channel = self.get_channel(restart_channel) if restart_channel else None
            await self.perform_update(channel)

    async def perform_update(self, channel=None):
        if self.shutting_down:
            return

        self.shutting_down = True
        if channel:
            await channel.send("Update initiated. Blocking new processing and waiting for current queue to finish...")

        async with self.global_llm_lock:
            if channel:
                await channel.send("Queue cleared. Fetching updates...")

            if getattr(sys, 'frozen', False):
                if not self.github_repo:
                    if channel:
                        await channel.send("Error: GITHUB_REPO not set in .env. Cannot download latest release.")
                    self.shutting_down = False
                    return

                system = platform.system().lower()
                async with aiohttp.ClientSession() as session:
                    url = f"https://api.github.com/repos/{self.github_repo}/releases/latest"
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            if channel:
                                await channel.send("Failed to find latest release on GitHub.")
                            self.shutting_down = False
                            return

                        data = await resp.json()
                        assets = data.get("assets", [])
                        asset_url = None
                        asset_name = None

                        for asset in assets:
                            if system in asset["name"].lower() and asset["name"].lower().endswith(".zip"):
                                asset_url = asset["browser_download_url"]
                                asset_name = asset["name"]
                                break

                        if not asset_url:
                            if channel:
                                await channel.send("Could not find a matching zip release asset for this OS.")
                            self.shutting_down = False
                            return

                        if channel:
                            await channel.send(f"Downloading new release package: {asset_name}...")

                        async with session.get(asset_url) as download_resp:
                            if download_resp.status == 200:
                                zip_path = "update_package.zip"
                                with open(zip_path, 'wb') as f:
                                    f.write(await download_resp.read())

                                try:
                                    extract_dir = "update_extracted"
                                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                                        zip_ref.extractall(extract_dir)

                                    source_dir = extract_dir
                                    if len(os.listdir(extract_dir)) == 1 and os.path.isdir(os.path.join(extract_dir, os.listdir(extract_dir)[0])):
                                        source_dir = os.path.join(extract_dir, os.listdir(extract_dir)[0])

                                    exe_path = sys.executable
                                    exe_name = os.path.basename(exe_path)

                                    for root, dirs, files in os.walk(source_dir):
                                        rel_path = os.path.relpath(root, source_dir)
                                        target_dir = os.path.join(os.getcwd(), rel_path) if rel_path != "." else os.getcwd()

                                        os.makedirs(target_dir, exist_ok=True)

                                        for file in files:
                                            src_file = os.path.join(root, file)
                                            if file == exe_name or (file.startswith("SoulClone") and "exe" in file):
                                                new_exe_path = f"{exe_path}.new"
                                                shutil.copy2(src_file, new_exe_path)
                                                if os.path.exists(f"{exe_path}.old"):
                                                    os.remove(f"{exe_path}.old")
                                                shutil.move(exe_path, f"{exe_path}.old")
                                                shutil.move(new_exe_path, exe_path)
                                                if system != "windows":
                                                    st = os.stat(exe_path)
                                                    os.chmod(exe_path, st.st_mode | stat.S_IEXEC)
                                            else:
                                                target_file = os.path.join(target_dir, file)
                                                shutil.copy2(src_file, target_file)

                                    shutil.rmtree(extract_dir)
                                    os.remove(zip_path)

                                except Exception as e:
                                    if channel:
                                        await channel.send(f"Error during extraction and file swap: {e}")
                                    self.shutting_down = False
                                    return
            else:
                process = await asyncio.create_subprocess_shell(
                    "git pull",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                if process.returncode != 0:
                    if channel:
                        await channel.send(f"Git pull failed:\n```\n{stderr.decode()}\n```")
                    self.shutting_down = False
                    return
                else:
                    if channel:
                        await channel.send(f"Git pull successful:\n```\n{stdout.decode()}\n```")

            if channel:
                await self._update_config("restart_channel_id", channel.id)
                await channel.send("Restarting bot to apply updates...")

            await self.close()

            # Remove PyInstaller environment variables to prevent MEIPASS conflicts on restart
            env = os.environ.copy()
            env.pop('_MEIPASS2', None)
            env.pop('_MEIPASS', None)

            if getattr(sys, 'frozen', False):
                os.execve(sys.executable, sys.argv, env)
            else:
                os.execve(sys.executable, [sys.executable] + sys.argv, env)

    async def update_bot_presence(self):
        enabled = self.bot_config.get("enabled", False)
        allowed_id = self.bot_config.get("allowed_channel_id")

        status_text = "Disabled"
        if enabled:
            if allowed_id:
                try:
                    channel = self.get_channel(allowed_id) or await self.fetch_channel(allowed_id)
                    name = f"#{channel.name}" if hasattr(channel, 'name') else str(allowed_id)
                    status_text = f"Restricted to {name}"
                except Exception:
                    status_text = f"Restricted to {allowed_id}"
            else:
                status_text = "Enabled in Server"

        status_type = discord.Status.online if enabled else discord.Status.idle

        new_hash = hash((status_text, status_type))
        if new_hash != self.current_status_hash:
            await self.change_presence(status=status_type, activity=discord.Game(name=status_text))
            self.current_status_hash = new_hash

    async def send_chunked_reply(self, message, text):
        if not text:
            return
        mentions = discord.AllowedMentions.none()
        for i in range(0, len(text), 1900):
            chunk = text[i:i + 1900]
            try:
                if i == 0:
                    await message.reply(chunk, allowed_mentions=mentions)
                else:
                    await message.channel.send(chunk, allowed_mentions=mentions)
                if len(text) > 1900:
                    await asyncio.sleep(0.5)
            except discord.HTTPException as e:
                print(f"Failed to send chunk: {e}")
                break

    async def send_chunked_message(self, channel, text):
        if not text:
            return
        mentions = discord.AllowedMentions.none()
        for i in range(0, len(text), 1900):
            chunk = text[i:i + 1900]
            try:
                await channel.send(chunk, allowed_mentions=mentions)
                if len(text) > 1900:
                    await asyncio.sleep(0.5)
            except discord.HTTPException as e:
                print(f"Failed to send chunk: {e}")
                break

    async def _resolve_persistent_queue(self):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute('''
                SELECT channel_id, timestamp, message_id
                FROM history h1
                WHERE timestamp = (SELECT MAX(timestamp) FROM history h2 WHERE h1.channel_id = h2.channel_id)
                AND role = 'user'
            ''') as cursor:
                rows = await cursor.fetchall()

        for channel_id, timestamp_str, message_id in rows:
            try:
                msg_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
                if time.time() - msg_time < self.bot_config.get("queue_expiration", 60):
                    original_message = None
                    if message_id:
                        channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
                        if channel:
                            try:
                                original_message = await channel.fetch_message(message_id)
                            except discord.HTTPException:
                                pass

                            if original_message:
                                try:
                                    await original_message.remove_reaction('💾', self.user)
                                except discord.HTTPException:
                                    pass
                                try:
                                    await original_message.add_reaction('⏳')
                                except discord.HTTPException:
                                    pass

                    asyncio.create_task(self.process_llm_queue(channel_id, msg_time, original_message=original_message))
            except Exception as e:
                print(f"Failed to process persistent queue for channel {channel_id}: {e}")

    async def on_ready(self):
        print(f'Logged in as {self.user}')
        await self.update_bot_presence()

        restart_channel_id = self.bot_config.get("restart_channel_id")
        if restart_channel_id:
            try:
                channel = self.get_channel(restart_channel_id) or await self.fetch_channel(restart_channel_id)
                if channel:
                    await channel.send("The bot has successfully restarted.")
            except Exception as e:
                print(f"Could not send restart message: {e}")
            finally:
                await self._update_config("restart_channel_id", None)

        await self._resolve_persistent_queue()

    async def process_llm_queue(self, channel_id, received_timestamp, original_message=None):
        async with self.global_llm_lock:
            expiration = self.bot_config.get("queue_expiration", 60)
            if time.time() - received_timestamp > expiration:
                if original_message:
                    try:
                        await original_message.remove_reaction('⏳', self.user)
                        await original_message.add_reaction('⚰')
                    except discord.HTTPException:
                        pass
                return

            channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
            if not channel:
                return

            async def keep_typing_loop():
                try:
                    while True:
                        async with channel.typing():
                            await asyncio.sleep(8)
                except asyncio.CancelledError:
                    pass

            typing_task = asyncio.create_task(keep_typing_loop())

            try:
                history = await self._get_history(channel_id)
                api_messages = [{"role": "system", "content": self.bot_config["system_prompt"]}]

                current_char_count = len(self.bot_config["system_prompt"])
                for msg in reversed(history):
                    if current_char_count + len(msg["content"]) > 12000:
                        break

                    if len(api_messages) > 1 and api_messages[1]["role"] == msg["role"]:
                        api_messages[1]["content"] = f"{msg['content']}\n{api_messages[1]['content']}"
                    else:
                        api_messages.insert(1, {"role": msg["role"], "content": msg["content"]})

                    current_char_count += len(msg["content"])

                response = await self.client.chat.completions.create(
                    model="local-model",
                    messages=api_messages
                )

                bot_reply = response.choices[0].message.content
                await self._add_to_history(channel_id, "assistant", bot_reply)

                clean_reply = bot_reply.replace(f"[{self.target_user}]:", "").strip()

                if original_message:
                    await self.send_chunked_reply(original_message, clean_reply)
                else:
                    await self.send_chunked_message(channel, clean_reply)

                self.bot_stats["messages_processed"] += 1

            except Exception as e:
                self.bot_stats["errors"] += 1
                await self._pop_last_history(channel_id)
                if original_message:
                    await original_message.reply(f"Error: {e}")
                else:
                    await channel.send(f"Error: {e}")

            finally:
                typing_task.cancel()
                if original_message:
                    try:
                        await original_message.remove_reaction('⏳', self.user)
                    except discord.HTTPException:
                        pass

    async def on_message(self, message):
        if message.author == self.user:
            return

        self.bot_stats["messages_seen"] += 1

        if message.content.startswith(self.command_prefix):
            await self.process_commands(message)
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        if is_dm:
            is_admin_dm = message.author.id == self.admin_user_id
            is_whitelisted = await self._is_whitelisted(message.author.id)
            if not is_admin_dm and not is_whitelisted:
                return

        allowed_id = self.bot_config["allowed_channel_id"]
        if not is_dm and allowed_id is not None and message.channel.id != allowed_id:
            return

        # Improved mention detection to catch raw tags and bypass API caching issues
        is_mentioned = self.user in message.mentions or f'<@{self.user.id}>' in message.content or f'<@!{self.user.id}>' in message.content
        should_reply = (is_mentioned or self.bot_config["reply_any_message"] or is_dm) and self.bot_config["enabled"]
        should_track = self.bot_config["track_non_mentions"]

        clean_input = message.content.replace(f'<@{self.user.id}>', '').replace(f'<@!{self.user.id}>', '').strip()
        if not clean_input and message.attachments:
            clean_input = "[Sent an attachment]"

        if not clean_input:
            return

        formatted_input = f"[{message.author.name}]: {clean_input}"

        if should_reply or should_track:
            await self._add_to_history(message.channel.id, "user", formatted_input, message.id)

            if should_reply:
                if self.shutting_down:
                    try:
                        await message.add_reaction('💾')
                    except discord.HTTPException:
                        pass
                else:
                    try:
                        await message.add_reaction('⏳')
                    except discord.HTTPException:
                        pass

                    received_at = time.time()
                    asyncio.create_task(self.process_llm_queue(message.channel.id, received_at, original_message=message))


def run_bot():
    bot = DiscordLLMBot()
    bot.run(bot.bot_token)


if __name__ == "__main__":
    run_bot()
