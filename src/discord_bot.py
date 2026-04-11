import os
import sys
import time
import aiosqlite
import discord
import asyncio
from discord.ext import commands
from openai import AsyncOpenAI
from dotenv import load_dotenv

# --- ADMIN CHECK DECORATOR ---
def is_admin():
    async def predicate(ctx):
        if ctx.author.name == ctx.bot.admin_user:
            return True
        await ctx.send("You do not have permission to use this command.")
        return False
    return commands.check(predicate)

# --- COMMANDS COG ---
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
        embed.add_field(name="Admin User", value=self.bot.admin_user or "None Set", inline=True)
        embed.add_field(name="Max History (Memory)", value=str(self.bot.bot_config["max_history"]), inline=True)
        embed.add_field(name="Track Non-Mentions", value=str(self.bot.bot_config["track_non_mentions"]), inline=True)
        embed.add_field(name="Bot Enabled", value=str(self.bot.bot_config["enabled"]), inline=True)
        embed.add_field(name="Any Message Mode", value=str(self.bot.bot_config["reply_any_message"]), inline=True)
        
        channel_name = "None (Any)"
        allowed_id = self.bot.bot_config["allowed_channel_id"]
        if allowed_id:
            try:
                # Fallback to fetch_channel if get_channel cache misses
                channel = self.bot.get_channel(allowed_id) or await self.bot.fetch_channel(allowed_id)
                channel_name = f"#{channel.name}" if hasattr(channel, 'name') else str(allowed_id)
            except (discord.NotFound, discord.HTTPException):
                channel_name = f"Unknown Channel ID ({allowed_id})"
                
        embed.add_field(name="Restricted Channel", value=channel_name, inline=True)
        embed.add_field(name="LLM Endpoint", value=self.bot.base_url, inline=False)
        
        # Added exact system prompt text to config output
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

    @commands.command(name="sh", aliases=["set_history", "hist"], help="[Admin] Set max history length. (;sh <num>)")
    @is_admin()
    async def set_history(self, ctx, length: int):
        if length < 1:
            await ctx.send("History length must be at least 1.")
            return
        await self.bot._update_config("max_history", length)
        await ctx.send(f"Max history set to {length} messages.")

    @commands.command(name="rc", aliases=["reset_config"], help="[Admin] Reset configuration to default values. (;rc)")
    @is_admin()
    async def reset_config(self, ctx):
        await self.bot._reset_to_defaults()
        await ctx.send("Bot configuration has been restored to default values.")

    @commands.command(name="rs", aliases=["restart"], help="[Admin] Restarts bot script. (;rs)")
    @is_admin()
    async def restart(self, ctx):
        await ctx.send("Restarting bot script...")
        await self.bot._update_config("restart_channel_id", ctx.channel.id)
        await self.bot.close()
        os.execv(sys.executable, ['python'] + sys.argv)

    @commands.command(name="sd", aliases=["shutdown", "kill"], help="[Admin] Shuts down bot. (;sd)")
    @is_admin()
    async def shutdown(self, ctx):
        await ctx.send("Shutting down...")
        await self.bot.close()
        sys.exit(0)

# --- MAIN BOT CLASS ---
class DiscordLLMBot(commands.Bot):
    def __init__(self):
        load_dotenv()
        
        # Configuration from environment
        self.target_user = os.getenv("TARGET_USER")
        self.bot_token = os.getenv("DISCORD_BOT_TOKEN")
        self.base_url = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
        self.api_key = os.getenv("LM_STUDIO_API_KEY", "lm-studio")
        self.admin_user = os.getenv("ADMIN_USER")
        
        if not self.bot_token or not self.target_user:
            print("Error: DISCORD_BOT_TOKEN and TARGET_USER must be set in your .env file.")
            sys.exit(1)

        self.system_prompt_default = f"You are {self.target_user} in a Discord chat."

        # Setup Intents
        intents = discord.Intents.default()
        intents.message_content = True
        
        super().__init__(command_prefix=";", intents=intents)

        # Initialization
        self.client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
        self.request_lock = asyncio.Lock()
        self.db_path = "bot_data.db"
        
        # State Initialization 
        self.bot_config = {}
        self.bot_stats = {
            "start_time": time.time(),
            "messages_seen": 0,
            "messages_processed": 0,
            "errors": 0
        }

    async def setup_hook(self):
        """Async setup executed before the bot connects to the gateway."""
        await self._init_db()
        await self._load_config()
        # Register the commands cog
        await self.add_cog(BotCommands(self))

    # --- DATABASE OPERATIONS ---

    async def _init_db(self):
        async with aiosqlite.connect(self.db_path) as conn:
            # Table for configuration/settings
            await conn.execute('''CREATE TABLE IF NOT EXISTS config 
                            (key TEXT PRIMARY KEY, value TEXT)''')
            # Table for conversation history
            await conn.execute('''CREATE TABLE IF NOT EXISTS history 
                            (channel_id INTEGER, role TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
            await conn.commit()

    async def _load_config(self):
        defaults = {
            "max_history": "15",
            "track_non_mentions": "False",
            "enabled": "False",
            "reply_any_message": "False",
            "allowed_channel_id": "None",
            "system_prompt": self.system_prompt_default,
            "restart_channel_id": "None"
        }
        
        async with aiosqlite.connect(self.db_path) as conn:
            for key, default in defaults.items():
                async with conn.execute("SELECT value FROM config WHERE key = ?", (key,)) as cursor:
                    row = await cursor.fetchone()
                    val_str = row[0] if row else default
                    
                    if not row:
                        await conn.execute("INSERT INTO config (key, value) VALUES (?, ?)", (key, default))
                
                # Cast database strings to appropriate python types
                if val_str in ("True", "False"):
                    self.bot_config[key] = (val_str == "True")
                elif key == "max_history":
                    self.bot_config[key] = int(val_str)
                elif key in ("allowed_channel_id", "restart_channel_id"):
                    self.bot_config[key] = int(val_str) if val_str != "None" else None
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
            "restart_channel_id": "None"
        }
        async with aiosqlite.connect(self.db_path) as conn:
            for key, default in defaults.items():
                await conn.execute("UPDATE config SET value = ? WHERE key = ?", (default, key))
                
                # Update local config dictionary
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

    async def _add_to_history(self, channel_id, role, content):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT INTO history (channel_id, role, content) VALUES (?, ?, ?)",
                         (channel_id, role, content))
            await conn.commit()

    async def _pop_last_history(self, channel_id):
        """Removes the most recent message in the database for a channel (used on API errors)."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM history WHERE rowid = (SELECT MAX(rowid) FROM history WHERE channel_id = ?)", (channel_id,))
            await conn.commit()

    async def _clear_history(self, channel_id):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM history WHERE channel_id = ?", (channel_id,))
            await conn.commit()

    # --- UTILITIES ---

    async def send_chunked_reply(self, message, text):
        """Splits long responses into Discord-friendly chunks of 2000 characters with rate-limit protection."""
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
                
                # Small delay to prevent Discord HTTP 429 Rate Limits on long generations
                if len(text) > 1900:
                    await asyncio.sleep(0.5)
            except discord.HTTPException as e:
                print(f"Failed to send chunk due to HTTP Exception: {e}")
                break

    async def on_ready(self):
        print(f'Successfully logged in as {self.user}')
        
        # Announce restart if recovering from a restart command
        restart_channel_id = self.bot_config.get("restart_channel_id")
        if restart_channel_id:
            try:
                channel = self.get_channel(restart_channel_id) or await self.fetch_channel(restart_channel_id)
                if channel:
                    await channel.send("The bot has successfully restarted and is back online.")
            except Exception as e:
                print(f"Could not send restart message: {e}")
            finally:
                await self._update_config("restart_channel_id", None)

    # --- MESSAGE PROCESSING ---

    async def on_message(self, message):
        if message.author == self.user:
            return
            
        self.bot_stats["messages_seen"] += 1

        # This correctly routes commands to the Cog
        if message.content.startswith(self.command_prefix):
            await self.process_commands(message)
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        if is_dm and message.author.name != self.admin_user:
            return

        # Channel restriction logic 
        allowed_id = self.bot_config["allowed_channel_id"]
        if not is_dm and allowed_id is not None and message.channel.id != allowed_id:
            return

        is_mentioned = self.user in message.mentions
        should_reply = (is_mentioned or self.bot_config["reply_any_message"] or is_dm) and self.bot_config["enabled"]
        should_save = should_reply or self.bot_config["track_non_mentions"]

        if should_save:
            clean_input = message.content.replace(f'<@{self.user.id}>', '').replace(f'<@!{self.user.id}>', '').strip()
            
            # Handle empty messages (attachments only)
            if not clean_input and message.attachments:
                clean_input = "[Sent an attachment]"
            elif not clean_input:
                return
            
            formatted_input = f"[{message.author.name}]: {clean_input}"
            await self._add_to_history(message.channel.id, "user", formatted_input)

        if should_reply:
            if self.request_lock.locked():
                await message.add_reaction("⏳")
            
            async with self.request_lock:
                try: 
                    await message.remove_reaction("⏳", self.user)
                except (discord.errors.NotFound, discord.errors.Forbidden): 
                    pass
                
                async def keep_typing():
                    try:
                        while True:
                            async with message.channel.typing():
                                await asyncio.sleep(8)
                    except asyncio.CancelledError:
                        pass
                
                typing_task = asyncio.create_task(keep_typing())
                
                try:
                    history = await self._get_history(message.channel.id)
                    api_messages = [{"role": "system", "content": self.bot_config["system_prompt"]}]
                    
                    # Context Window / Character Limit Pruning
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
                    await self._add_to_history(message.channel.id, "assistant", bot_reply)
                    
                    clean_reply = bot_reply.replace(f"[{self.target_user}]:", "").strip()
                    await self.send_chunked_reply(message, clean_reply)
                    self.bot_stats["messages_processed"] += 1

                except Exception as e:
                    self.bot_stats["errors"] += 1
                    # Remove the failing user message from the database so it doesn't break future context
                    await self._pop_last_history(message.channel.id)
                    await message.reply(f"Error communicating with local server: {e}")
                
                finally:
                    typing_task.cancel()

def run_bot():
    bot = DiscordLLMBot()
    bot.run(bot.bot_token)

if __name__ == "__main__":
    run_bot()