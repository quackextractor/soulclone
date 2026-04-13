"""
Core bot initialization and message processing logic.
Handles the main event loop, LLM queuing, and chunked discord replies.
"""
import os
import sys
import time
import asyncio
import discord
from discord.ext import commands
from openai import AsyncOpenAI
from dotenv import load_dotenv

from src.bot.database import BotDatabase
from src.bot.commands import BotCommands


class DiscordLLMBot(commands.Bot):
    def __init__(self):
        load_dotenv()

        self.target_user = os.getenv("TARGET_USER")
        self.bot_token = os.getenv("DISCORD_BOT_TOKEN")
        self.base_url = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
        self.api_key = os.getenv("LM_STUDIO_API_KEY", "lm-studio")
        self.admin_user_id = int(os.getenv("ADMIN_USER_ID", 0))
        self.current_status_hash = None

        if not self.bot_token or not self.target_user:
            print("Error: DISCORD_BOT_TOKEN and TARGET_USER must be set in your .env file.")
            sys.exit(1)

        self.system_prompt_default = f"You are {self.target_user} in a Discord chat."

        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(command_prefix=";", intents=intents)

        self.client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
        self.global_llm_lock = asyncio.Lock()

        self.db = BotDatabase("bot_data.db", self.system_prompt_default)

        self.bot_stats = {
            "start_time": time.time(),
            "messages_seen": 0,
            "messages_processed": 0,
            "errors": 0
        }

    async def setup_hook(self):
        await self.db.init_db()
        await self.db.load_config()
        await self.add_cog(BotCommands(self))

    async def update_bot_presence(self):
        enabled = self.db.config.get("enabled", False)
        allowed_id = self.db.config.get("allowed_channel_id")

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

        # Hash check to avoid rate limits
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

    async def on_ready(self):
        print(f'Logged in as {self.user}')
        await self.update_bot_presence()

        restart_channel_id = self.db.config.get("restart_channel_id")
        if restart_channel_id:
            try:
                channel = self.get_channel(restart_channel_id) or await self.fetch_channel(restart_channel_id)
                if channel:
                    await channel.send("The bot has successfully restarted.")
            except Exception as e:
                print(f"Could not send restart message: {e}")
            finally:
                await self.db.update_config("restart_channel_id", None)

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
            is_whitelisted = await self.db.is_whitelisted(message.author.id)
            if not is_admin_dm and not is_whitelisted:
                return

        allowed_id = self.db.config.get("allowed_channel_id")
        if not is_dm and allowed_id is not None and message.channel.id != allowed_id:
            return

        is_mentioned = self.user in message.mentions
        should_reply = (is_mentioned or self.db.config.get("reply_any_message") or is_dm) and self.db.config.get("enabled")
        should_track = self.db.config.get("track_non_mentions")

        # Formatting logic for the message
        clean_input = message.content.replace(f'<@{self.user.id}>', '').replace(f'<@!{self.user.id}>', '').strip()
        if not clean_input and message.attachments:
            clean_input = "[Sent an attachment]"

        if not clean_input:
            return

        formatted_input = f"[{message.author.name}]: {clean_input}"

        if should_reply:
            # 1. Immediate visual feedback
            try:
                await message.add_reaction('⏳')
            except discord.HTTPException:
                pass

            # 2. Global lock to protect hardware
            received_at = time.time()
            async with self.global_llm_lock:
                # Check for queue expiration
                expiration = self.db.config.get("queue_expiration", 60)
                if time.time() - received_at > expiration:
                    try:
                        await message.remove_reaction('⏳', self.user)
                        await message.add_reaction('⚰')
                    except discord.HTTPException:
                        pass
                    return

                await self.db.add_to_history(message.channel.id, "user", formatted_input)

                async def keep_typing_loop():
                    try:
                        while True:
                            async with message.channel.typing():
                                await asyncio.sleep(8)
                    except asyncio.CancelledError:
                        pass

                typing_task = asyncio.create_task(keep_typing_loop())

                try:
                    history = await self.db.get_history(message.channel.id)
                    api_messages = [{"role": "system", "content": self.db.config.get("system_prompt", self.system_prompt_default)}]

                    current_char_count = len(api_messages[0]["content"])
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
                    await self.db.add_to_history(message.channel.id, "assistant", bot_reply)

                    clean_reply = bot_reply.replace(f"[{self.target_user}]:", "").strip()
                    await self.send_chunked_reply(message, clean_reply)
                    self.bot_stats["messages_processed"] += 1

                except Exception as e:
                    self.bot_stats["errors"] += 1
                    await self.db.pop_last_history(message.channel.id)
                    await message.reply(f"Error: {e}")

                finally:
                    typing_task.cancel()
                    # 3. Clean up reaction
                    try:
                        await message.remove_reaction('⏳', self.user)
                    except discord.HTTPException:
                        pass

        elif should_track:
            # Passive tracking happens outside locks to keep the DB updated without blocking
            await self.db.add_to_history(message.channel.id, "user", formatted_input)


def run_bot():
    bot = DiscordLLMBot()
    bot.run(bot.bot_token)
