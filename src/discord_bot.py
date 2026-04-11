import os
import sys
import time
import sqlite3
import discord
import asyncio
import json
from collections import deque
from discord.ext import commands, tasks
from openai import AsyncOpenAI
from dotenv import load_dotenv

class DiscordLLMBot(commands.Bot):
    def __init__(self):
        load_dotenv()
        
        # Configuration from environment
        self.target_user = os.getenv("TARGET_USER")
        self.bot_token = os.getenv("DISCORD_BOT_TOKEN")
        self.base_url = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
        self.api_key = os.getenv("LM_STUDIO_API_KEY", "lm-studio")
        self.admin_user = os.getenv("ADMIN_USER")
        self.system_prompt_default = f"You are {self.target_user} in a Discord chat."

        # Setup Intents
        intents = discord.Intents.default()
        intents.message_content = True
        
        super().__init__(command_prefix="!", intents=intents)

        # Initialization
        self.client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
        self.request_lock = asyncio.Lock()
        self.db_path = "bot_data.db"
        self._init_db()
        
        # Load volatile state from DB
        self.bot_config = self._load_config()
        self.bot_stats = {
            "start_time": time.time(),
            "messages_processed": 0,
            "errors": 0
        }

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Table for configuration/settings
            cursor.execute('''CREATE TABLE IF NOT EXISTS config 
                            (key TEXT PRIMARY KEY, value TEXT)''')
            # Table for conversation history
            cursor.execute('''CREATE TABLE IF NOT EXISTS history 
                            (channel_id INTEGER, role TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
            conn.commit()

    def _load_config(self):
        defaults = {
            "max_history": 15,
            "track_non_mentions": "False",
            "enabled": "False",
            "reply_any_message": "False",
            "allowed_channel_id": "None",
            "system_prompt": self.system_prompt_default
        }
        config = {}
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for key, default in defaults.items():
                cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row:
                    config[key] = row[0]
                else:
                    cursor.execute("INSERT INTO config (key, value) VALUES (?, ?)", (key, default))
                    config[key] = default
            conn.commit()
        return config

    def _update_config(self, key, value):
        self.bot_config[key] = str(value)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE config SET value = ? WHERE key = ?", (str(value), key))
            conn.commit()

    def _get_history(self, channel_id):
        max_h = int(self.bot_config["max_history"])
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""SELECT role, content FROM (
                                SELECT role, content, timestamp FROM history 
                                WHERE channel_id = ? 
                                ORDER BY timestamp DESC LIMIT ?
                              ) ORDER BY timestamp ASC""", (channel_id, max_h))
            return [{"role": row[0], "content": row[1]} for row in cursor.fetchall()]

    def _add_to_history(self, channel_id, role, content):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO history (channel_id, role, content) VALUES (?, ?, ?)",
                         (channel_id, role, content))
            conn.commit()

    def _clear_history(self, channel_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM history WHERE channel_id = ?", (channel_id,))
            conn.commit()

    async def send_chunked_reply(self, message, text):
        """Splits long responses into Discord-friendly chunks of 2000 characters."""
        if not text:
            return
        
        # Define allowed_mentions=none to prevent mass pings
        mentions = discord.AllowedMentions.none()
        
        for i in range(0, len(text), 1900):
            chunk = text[i:i + 1900]
            if i == 0:
                await message.reply(chunk, allowed_mentions=mentions)
            else:
                await message.channel.send(chunk, allowed_mentions=mentions)

    async def on_ready(self):
        print(f'Successfully logged in as {self.user}')

    # --- ADMIN CHECK ---
    def is_admin_check(self, ctx):
        return ctx.author.name == self.admin_user

    # --- COMMANDS ---

    @commands.command(name="reset")
    async def reset_memory(self, ctx):
        self._clear_history(ctx.channel.id)
        await ctx.send("Memory wiped for this channel.")

    @commands.command(name="stats")
    async def show_stats(self, ctx):
        uptime = int(time.time() - self.bot_stats["start_time"])
        mins, secs = divmod(uptime, 60)
        hours, mins = divmod(mins, 60)
        
        embed = discord.Embed(title="Bot Statistics", color=discord.Color.blue())
        embed.add_field(name="Uptime", value=f"{hours}h {mins}m {secs}s", inline=True)
        embed.add_field(name="Processed", value=str(self.bot_stats["messages_processed"]), inline=True)
        embed.add_field(name="Errors", value=str(self.bot_stats["errors"]), inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="set_prompt")
    async def set_prompt(self, ctx, *, new_prompt: str):
        if not self.is_admin_check(ctx): return
        self._update_config("system_prompt", new_prompt)
        await ctx.send("System prompt updated successfully.")

    @commands.command(name="toggle_bot")
    async def toggle_bot(self, ctx):
        if not self.is_admin_check(ctx): return
        new_state = "False" if self.bot_config["enabled"] == "True" else "True"
        self._update_config("enabled", new_state)
        await ctx.send(f"Bot answering is now **{new_state}**.")

    @commands.command(name="set_history")
    async def set_history(self, ctx, length: int):
        if not self.is_admin_check(ctx): return
        self._update_config("max_history", length)
        await ctx.send(f"Max history set to {length} messages.")

    @commands.command(name="restart")
    async def restart(self, ctx):
        if not self.is_admin_check(ctx): return
        await ctx.send("Restarting bot script...")
        await self.close()
        os.execv(sys.executable, ['python'] + sys.argv)

    @commands.command(name="shutdown")
    async def shutdown(self, ctx):
        if not self.is_admin_check(ctx): return
        await ctx.send("Shutting down...")
        await self.close()
        sys.exit(0)

    # --- MESSAGE PROCESSING ---

    async def on_message(self, message):
        if message.author == self.user:
            return

        if message.content.startswith(self.command_prefix):
            await self.process_commands(message)
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        if is_dm and message.author.name != self.admin_user:
            return

        # Channel restriction logic
        allowed_id = self.bot_config["allowed_channel_id"]
        if not is_dm and allowed_id != "None" and message.channel.id != int(allowed_id):
            return

        is_mentioned = self.user in message.mentions
        should_reply = (is_mentioned or self.bot_config["reply_any_message"] == "True" or is_dm) and self.bot_config["enabled"] == "True"
        should_save = should_reply or self.bot_config["track_non_mentions"] == "True"

        if should_save:
            clean_input = message.content.replace(f'<@{self.user.id}>', '').replace(f'<@!{self.user.id}>', '').strip()
            # Handle empty messages (attachments only)
            if not clean_input and message.attachments:
                clean_input = "[Sent an attachment]"
            
            formatted_input = f"[{message.author.name}]: {clean_input}"
            self._add_to_history(message.channel.id, "user", formatted_input)

        if should_reply:
            if self.request_lock.locked():
                await message.add_reaction("⏳")
            
            async with self.request_lock:
                # Remove reaction if it was added
                if any(r.emoji == "⏳" for r in message.reactions):
                    try: await message.remove_reaction("⏳", self.user)
                    except: pass
                
                async with message.channel.typing():
                    try:
                        history = self._get_history(message.channel.id)
                        api_messages = [{"role": "system", "content": self.bot_config["system_prompt"]}]
                        
                        # Context Window / Character Limit Pruning (Basic heuristic)
                        # We keep character count under ~12,000 for local context safety
                        current_char_count = len(self.bot_config["system_prompt"])
                        for msg in reversed(history):
                            if current_char_count + len(msg["content"]) > 12000:
                                break
                            
                            # Merge consecutive roles
                            if api_messages and api_messages[-1]["role"] == msg["role"]:
                                api_messages[-1]["content"] = f"{msg['content']}\n{api_messages[-1]['content']}"
                            else:
                                api_messages.insert(1, {"role": msg["role"], "content": msg["content"]})
                            current_char_count += len(msg["content"])

                        response = await self.client.chat.completions.create(
                            model="local-model",
                            messages=api_messages
                        )

                        bot_reply = response.choices[0].message.content
                        self._add_to_history(message.channel.id, "assistant", bot_reply)
                        
                        clean_reply = bot_reply.replace(f"[{self.target_user}]:", "").strip()
                        await self.send_chunked_reply(message, clean_reply)
                        self.bot_stats["messages_processed"] += 1

                    except Exception as e:
                        self.bot_stats["errors"] += 1
                        await message.reply(f"Error communicating with local server: {e}")

if __name__ == "__main__":
    bot = DiscordLLMBot()
    bot.run(bot.bot_token)