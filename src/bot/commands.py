"""
Discord bot commands and administrative controls.
Contains the primary Cog for user interactions and settings adjustments.
"""
import os
import sys
import time
import discord
import platform
import aiohttp
import tempfile
import zipfile
import shutil
import asyncio
import random
import yaml
from discord.ext import commands
import subprocess
from src.downloader import fast_isolated_download


def is_admin():
    """Decorator to restrict command usage to the bot administrator."""
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
        await self.bot.db.clear_history(ctx.channel.id)
        channel_name = "DM" if isinstance(ctx.channel, discord.DMChannel) else f"#{ctx.channel.name}"
        await ctx.send(f"Memory wiped for {channel_name}. Starting fresh.")

    @commands.command(name="s", aliases=["stats"], help="Shows bot stats. (;s)")
    async def show_stats(self, ctx):
        uptime = int(time.time() - self.bot.bot_stats["start_time"])
        mins, secs = divmod(uptime, 60)
        hours, mins = divmod(mins, 60)

        history = await self.bot.db.get_history(ctx.channel.id)

        embed = discord.Embed(title="Bot Statistics", color=discord.Color.blue())
        embed.add_field(name="Uptime", value=f"{hours}h {mins}m {secs}s", inline=False)
        embed.add_field(name="Messages Seen", value=str(self.bot.bot_stats["messages_seen"]), inline=True)
        embed.add_field(name="Processed", value=str(self.bot.bot_stats["messages_processed"]), inline=True)
        embed.add_field(name="Errors", value=str(self.bot.bot_stats["errors"]), inline=True)
        embed.add_field(name="Current Channel Memory", value=f"{len(history)} / {self.bot.db.config['max_history']} msgs", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="c", aliases=["config", "cfg"], help="Displays current bot parameters. (;c)")
    async def show_config(self, ctx):
        embed = discord.Embed(title="Bot Configuration", color=discord.Color.green())
        embed.add_field(name="Target User Persona", value=self.bot.target_user, inline=True)
        embed.add_field(name="Admin User", value=getattr(self.bot, 'admin_user', str(self.bot.admin_user_id)), inline=True)
        embed.add_field(name="Max History (Memory)", value=str(self.bot.db.config["max_history"]), inline=True)
        embed.add_field(name="Track Non-Mentions", value=str(self.bot.db.config["track_non_mentions"]), inline=True)
        embed.add_field(name="Bot Enabled", value=str(self.bot.db.config["enabled"]), inline=True)
        embed.add_field(name="Any Message Mode", value=str(self.bot.db.config["reply_any_message"]), inline=True)
        embed.add_field(name="Long-Term Memory (RAG)", value=str(self.bot.db.config.get("use_rag", False)), inline=True)
        embed.add_field(name="Queue Expiration", value=f"{self.bot.db.config['queue_expiration']}s", inline=True)
        embed.add_field(name="Environment Context", value=str(self.bot.db.config.get("use_environment_context", False)), inline=True)

        channel_name = "None (Any)"
        allowed_id = self.bot.db.config["allowed_channel_id"]
        if allowed_id:
            try:
                channel = self.bot.get_channel(allowed_id) or await self.bot.fetch_channel(allowed_id)
                channel_name = f"#{channel.name}" if hasattr(channel, 'name') else str(allowed_id)
            except (discord.NotFound, discord.HTTPException):
                channel_name = f"Unknown Channel ID ({allowed_id})"

        embed.add_field(name="Restricted Channel", value=channel_name, inline=True)
        embed.add_field(name="LLM Endpoint", value=self.bot.base_url, inline=False)

        prompt_text = self.bot.db.config.get("system_prompt", "None")
        if len(prompt_text) > 1000:
            prompt_text = prompt_text[:1000] + "... [Truncated]"
        embed.add_field(name="Current System Prompt", value=f"```\n{prompt_text}\n```", inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="sp", aliases=["set_prompt", "prompt"], help="[Admin] Set system prompt. (;sp <prompt>)")
    @is_admin()
    async def set_prompt(self, ctx, *, new_prompt: str):
        await self.bot.db.update_config("system_prompt", new_prompt)
        await ctx.send("System prompt updated successfully.")

    @commands.command(name="tb", aliases=["toggle_bot", "on", "off"], help="[Admin] Toggle replies. (;tb)")
    @is_admin()
    async def toggle_bot(self, ctx):
        new_state = not self.bot.db.config["enabled"]
        await self.bot.db.update_config("enabled", new_state)
        await self.bot.update_bot_presence()
        state_str = "ON" if new_state else "OFF"
        await ctx.send(f"Bot answering is now **{state_str}**.")

    @commands.command(name="tt", aliases=["toggle_tracking", "track"], help="[Admin] Toggle non-mention tracking. (;tt)")
    @is_admin()
    async def toggle_tracking(self, ctx):
        new_state = not self.bot.db.config["track_non_mentions"]
        await self.bot.db.update_config("track_non_mentions", new_state)
        state_str = "ON" if new_state else "OFF"
        await ctx.send(f"Tracking of non-mention messages is now **{state_str}**.")

    @commands.command(name="ta", aliases=["toggle_anymessage", "any"], help="[Admin] Toggle 'any message' mode. (;ta)")
    @is_admin()
    async def toggle_anymessage(self, ctx):
        new_state = not self.bot.db.config["reply_any_message"]
        await self.bot.db.update_config("reply_any_message", new_state)
        state_str = "ON" if new_state else "OFF"
        await ctx.send(f"Any message mode is now **{state_str}**.")

    @commands.command(name="te", aliases=["toggle_env", "env"], help="[Admin] Toggle environment awareness. (;te)")
    @is_admin()
    async def toggle_env(self, ctx):
        new_state = not self.bot.db.config.get("use_environment_context", False)
        await self.bot.db.update_config("use_environment_context", new_state)
        state_str = "ON" if new_state else "OFF"
        await ctx.send(f"Environment and time awareness is now **{state_str}**.")

    @commands.command(name="sc", aliases=["set_channel", "chan"], help="[Admin] Restrict to channel. 'clear' to undo. (;sc)")
    @is_admin()
    async def set_channel(self, ctx, arg: str = None):
        if arg and arg.lower() == "clear":
            await self.bot.db.update_config("allowed_channel_id", None)
            await ctx.send("Channel restriction removed. The bot can now reply in any channel.")
        else:
            await self.bot.db.update_config("allowed_channel_id", ctx.channel.id)
            channel_name = "DM" if isinstance(ctx.channel, discord.DMChannel) else f"#{ctx.channel.name}"
            await ctx.send(f"Bot is now restricted to channel: {channel_name}")

    @commands.command(name="sh", aliases=["set_history", "hist"], help="[Admin] Set max history length. (;sh <num>)")
    @is_admin()
    async def set_history(self, ctx, length: int):
        if length < 1:
            await ctx.send("History length must be at least 1.")
            return
        await self.bot.db.update_config("max_history", length)
        await ctx.send(f"Max history set to {length} messages.")

    @commands.command(name="tr", aliases=["toggle_rag", "rag"], help="[Admin] Toggle Long-Term Memory (RAG). (;tr)")
    @is_admin()
    async def toggle_rag(self, ctx):
        new_state = not self.bot.db.config.get("use_rag", False)
        await self.bot.db.update_config("use_rag", new_state)
        state_str = "ON" if new_state else "OFF"
        await ctx.send(f"Long-Term Memory (RAG) is now **{state_str}**.")

    @commands.command(name="cr", aliases=["clear_rag"], help="[Admin] Clear Long-Term Memory for this channel. (;cr)")
    @is_admin()
    async def clear_rag(self, ctx):
        await self.bot.rag_memory.clear_memory(ctx.channel.id)
        channel_name = "DM" if isinstance(ctx.channel, discord.DMChannel) else f"#{ctx.channel.name}"
        await ctx.send(f"Long-Term Vector Memory wiped for {channel_name}.")

    @commands.group(name="whitelist", help="[Admin] Manage DM whitelist. (;whitelist <add|remove|list>)")
    @is_admin()
    async def whitelist(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("Usage: `;whitelist <add|remove|list> [user_id]`")

    @whitelist.command(name="add")
    @is_admin()
    async def whitelist_add(self, ctx, user_id: int):
        await self.bot.db.add_whitelist(user_id)
        await ctx.send(f"User ID `{user_id}` has been added to the DM whitelist.")

    @whitelist.command(name="remove")
    @is_admin()
    async def whitelist_remove(self, ctx, user_id: int):
        await self.bot.db.remove_whitelist(user_id)
        await ctx.send(f"User ID `{user_id}` has been removed from the DM whitelist.")

    @whitelist.command(name="list")
    @is_admin()
    async def whitelist_list(self, ctx):
        wl = await self.bot.db.get_whitelist()
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
        await self.bot.db.update_config("queue_expiration", seconds)
        await ctx.send(f"Queue expiration set to {seconds} seconds.")

    @commands.command(name="rc", aliases=["reset_config"], help="[Admin] Reset configuration to default values. (;rc)")
    @is_admin()
    async def reset_config(self, ctx):
        await self.bot.db.reset_to_defaults()
        await self.bot.update_bot_presence()
        await ctx.send("Bot configuration has been restored to default values.")

    @commands.command(name="tg", aliases=["toggle_gif"], help="[Admin] Set GIF mode (0:Off, 1:JSON, 2:Giphy, 3:Mix). (;tg <0-3>)")
    @is_admin()
    async def toggle_gif(self, ctx, mode: int):
        if mode not in [0, 1, 2, 3]:
            await ctx.send("Invalid mode. Use 0 (Off), 1 (JSON), 2 (Giphy), or 3 (Mix).")
            return
        await self.bot.db.update_config("gif_mode", str(mode))

        modes = {0: "Off", 1: "JSON Only", 2: "Giphy Search Only", 3: "Mix (JSON + Giphy)"}
        await ctx.send(f"GIF reaction mode set to: **{modes[mode]}**")

    @commands.command(name="st", aliases=["set_triggers"], help="[Admin] Set comma-separated trigger phrases. (;st phrase1, phrase2)")
    @is_admin()
    async def set_triggers(self, ctx, *, triggers: str):
        if not triggers:
            await ctx.send("Please provide a comma-separated list of triggers.")
            return
        await self.bot.db.update_config("gif_triggers", triggers.lower())
        await ctx.send(f"GIF triggers updated to: `{triggers}`")

    @commands.command(name="randomgif", aliases=["rgif", "gif"], help="Sends a random GIF based on the active mode. (;randomgif [search_term])")
    async def random_gif(self, ctx, *, search_term: str = None):
        gif_mode = int(self.bot.db.config.get("gif_mode", "0"))

        if gif_mode == 0:
            await ctx.send("GIF reactions are currently disabled. An admin can enable them with `;tg <1-3>`.")
            return

        if not search_term:
            search_term = random.choice(["reaction", "funny", "idk", "what", "bruh", "wow"])

        gif_url = await self.bot.fetch_reaction_gif(gif_mode, search_term)

        if gif_url:
            await ctx.send(gif_url)
        else:
            await ctx.send("Failed to fetch a GIF. Please check the bot's console for errors or missing API keys.")

    @commands.command(name="update", aliases=["up"], help="[Admin] Auto-updates the bot to the latest version. (;update)")
    @is_admin()
    async def update_bot(self, ctx):
        repo = os.getenv("GITHUB_REPO")
        if not repo:
            await ctx.send("Update failed. GITHUB_REPO is not defined in the .env file.")
            return

        await ctx.send("Initiating background update. Processing will continue normally until the payload is ready...")

        try:
            if getattr(sys, 'frozen', False):
                await self._update_binary(ctx, repo)
            else:
                await self._update_source(ctx)
        except Exception as e:
            await ctx.send(f"Update encountered a critical failure:\n```\n{e}\n```")
            self.bot.pause_queue = False

    async def _update_source(self, ctx):
        """Updates the local python repository using git pull."""
        process = await asyncio.create_subprocess_shell(
            "git pull",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            await ctx.send("Git pull complete. Pausing queue and waiting for active generation to finish...")

            # Lock the queue from taking new jobs
            self.bot.pause_queue = True
            async with self.bot.global_llm_lock:
                await ctx.send("Queue paused safely. Restarting framework...")
                await self.restart(ctx)
        else:
            await ctx.send(f"Git pull failed. Ensure git is installed and repository is accessible:\n```\n{stderr.decode()}\n```")

    async def _update_binary(self, ctx, repo):
        """Fetches, extracts, and hot-swaps the compiled release package."""
        is_windows = platform.system() == "Windows"
        target_keyword = "Windows" if is_windows else "Linux"
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status != 200:
                    await ctx.send(f"Failed to fetch release metadata. HTTP Status: {resp.status}")
                    return
                release_data = await resp.json()

        assets = release_data.get("assets", [])
        download_url = None
        for asset in assets:
            if target_keyword in asset["name"] and asset["name"].endswith(".zip"):
                download_url = asset["browser_download_url"]
                break

        if not download_url:
            await ctx.send(f"No suitable zip asset found for {target_keyword} in the latest release.")
            return

        await ctx.send(f"Found latest {target_keyword} release. Downloading payload via native parallel connections...")

        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "update.zip")
            extract_path = os.path.join(temp_dir, "extracted")

            try:
                with open("config.yaml", "r", encoding="utf-8") as f:
                    file_config = yaml.safe_load(f)
            except Exception:
                file_config = {}

            success = await asyncio.to_thread(fast_isolated_download, download_url, temp_dir, "update.zip", file_config)

            if not success:
                await ctx.send("Native parallel download failed.")
                return

            # Extract the downloaded zip
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_path)

            target_source_dir = extract_path
            possible_wrapper = os.path.join(extract_path, "release_pkg")
            if os.path.exists(possible_wrapper) and os.path.isdir(possible_wrapper):
                target_source_dir = possible_wrapper

            await ctx.send("Download and extraction complete. Pausing queue and waiting for active generation to finish...")

            # Lock the queue and wait for the LLM to yield
            self.bot.pause_queue = True
            async with self.bot.global_llm_lock:
                await ctx.send("Queue paused safely. Applying files...")

                current_exe = sys.executable
                old_exe = current_exe + ".old"
                if os.path.exists(old_exe):
                    os.remove(old_exe)
                os.rename(current_exe, old_exe)

                work_dir = os.path.dirname(current_exe)
                for item in os.listdir(target_source_dir):
                    source_item = os.path.join(target_source_dir, item)
                    dest_item = os.path.join(work_dir, item)

                    if item == ".env":
                        continue

                    if os.path.isdir(source_item):
                        if os.path.exists(dest_item):
                            shutil.rmtree(dest_item)
                        shutil.copytree(source_item, dest_item)
                    else:
                        shutil.copy2(source_item, dest_item)

                if not is_windows:
                    new_exe = os.path.join(work_dir, os.path.basename(current_exe))
                    if os.path.exists(new_exe):
                        os.chmod(new_exe, 0o755)

                await ctx.send("Update fully applied. Restarting framework...")
                await self.restart(ctx)

    @commands.command(name="rs", aliases=["restart"], help="[Admin] Restarts bot script. (;rs)")
    @is_admin()
    async def restart(self, ctx):
        """
        Saves the current channel ID for the restart message, sets the bot
        status to offline, and re-executes the main process.
        """
        await ctx.send("Restarting bot script...")
        await self.bot.db.update_config("restart_channel_id", ctx.channel.id)
        await self.bot.change_presence(status=discord.Status.offline)
        await self.bot.close()

        if getattr(sys, 'frozen', False):
            env = os.environ.copy()
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            subprocess.Popen([sys.executable] + sys.argv[1:], env=env)
            os._exit(0)
        else:
            os.execv(sys.executable, ['python'] + sys.argv)

    @commands.command(name="sd", aliases=["shutdown", "kill"], help="[Admin] Shuts down bot. (;sd)")
    @is_admin()
    async def shutdown(self, ctx):
        """
        Sets the bot status to offline and terminates the process completely.
        """
        await ctx.send("Shutting down...")
        await self.bot.change_presence(status=discord.Status.offline)
        await self.bot.close()
        os._exit(0)
