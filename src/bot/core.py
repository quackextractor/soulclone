"""
Core bot initialization and message processing logic.
Handles the main event loop, LLM queuing, and chunked discord replies.
"""
import os
import sys
import time
import datetime
import asyncio
import discord
import json
import random
import aiohttp
from discord.ext import commands
from openai import AsyncOpenAI
from dotenv import load_dotenv

from src.bot.database import BotDatabase
from src.bot.commands import BotCommands
from src.bot.memory import LongTermMemory


class DiscordLLMBot(commands.Bot):
    def __init__(self):
        load_dotenv()

        self.target_user = os.getenv("TARGET_USER")
        self.bot_token = os.getenv("DISCORD_BOT_TOKEN")
        self.base_url = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
        self.api_key = os.getenv("LM_STUDIO_API_KEY", "lm-studio")
        self.admin_user_id = int(os.getenv("ADMIN_USER_ID", 0))
        self.gif_source_dir = os.getenv("GIF_SOURCE_DIR")
        self.giphy_api_key = os.getenv("GIPHY_API_KEY")
        self.current_status_hash = None

        self.shutting_down = False
        self.pause_queue = False
        self.generation_queue = asyncio.Queue()

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
        self.rag_memory = LongTermMemory()

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

        # Load persistent queue on startup
        queued_msgs = await self.db.get_queued_messages()
        for msg in queued_msgs:
            await self.generation_queue.put(msg)

        # Start the background processor
        self.loop.create_task(self.process_queue())

        if getattr(sys, 'frozen', False):
            old_exe = sys.executable + ".old"
            if os.path.exists(old_exe):
                try:
                    os.remove(old_exe)
                except Exception as e:
                    print(f"Cleanup non-critical error: {e}")

    async def fetch_reaction_gif(self, mode: int, trigger_phrase: str):
        """Fetches a GIF based on the active mode."""
        choice = mode
        if mode == 3:
            choice = random.choice([1, 2])

        if choice == 1:
            if not self.gif_source_dir or not os.path.exists(self.gif_source_dir):
                print("Error: GIF_SOURCE_DIR is invalid or missing.")
                return None
            try:
                with open(self.gif_source_dir, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                gifs = data.get("favoriteGifs", {}).get("gifs", {})
                if not gifs:
                    return None
                selected = random.choice(list(gifs.values()))
                return selected.get("src")
            except Exception as e:
                print(f"Error loading JSON GIFs: {e}")
                return None

        elif choice == 2:
            if not self.giphy_api_key:
                print("Error: GIPHY_API_KEY is missing.")
                return None

            search_query = trigger_phrase.replace(" ", "+")
            # Using Giphy's public search endpoint with a pg-13 rating filter
            url = f"https://api.giphy.com/v1/gifs/search?api_key={self.giphy_api_key}&q={search_query}&limit=15&rating=pg-13"

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get("data", [])
                            if results:
                                # Giphy's JSON structure requires digging into images -> original -> url
                                return random.choice(results)["images"]["original"]["url"]
            except Exception as e:
                print(f"Error fetching Giphy GIF: {e}")
                return None

        return None

    async def process_queue(self):
        await self.wait_until_ready()

        while not self.is_closed():
            if self.pause_queue:
                await asyncio.sleep(1)
                continue

            try:
                msg_data = await self.generation_queue.get()
                message_id, channel_id, author_name, clean_input, received_at = msg_data

                # Re-fetch the message and channel
                try:
                    channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
                    message = await channel.fetch_message(message_id)
                except discord.NotFound:
                    # Message was deleted while in queue
                    await self.db.dequeue_message(message_id)
                    continue

                # Expiration Check 1
                expiration = self.db.config.get("queue_expiration", 60)
                if time.time() - received_at > expiration:
                    try:
                        await message.add_reaction('⚰️')
                    except discord.HTTPException:
                        pass
                    try:
                        await message.remove_reaction('⏳', self.user)
                    except discord.HTTPException:
                        pass
                    await self.db.dequeue_message(message_id)
                    continue

                # Transition to Processing State (Eye Emoji)
                try:
                    await message.add_reaction('👀')
                except discord.HTTPException:
                    pass
                try:
                    await message.remove_reaction('⏳', self.user)
                except discord.HTTPException:
                    pass

                # Wait for the GPU to be free
                async with self.global_llm_lock:
                    # Expiration Check 2 (In case it sat in the lock for too long)
                    if time.time() - received_at > expiration:
                        try:
                            await message.add_reaction('⚰️')
                        except discord.HTTPException:
                            pass
                        try:
                            await message.remove_reaction('👀', self.user)
                        except discord.HTTPException:
                            pass
                        await self.db.dequeue_message(message_id)
                        continue

                    # Insert user message into context right before generating to keep turns ordered perfectly
                    formatted_input = f"[{author_name}]: {clean_input}"

                    if self.db.config.get("use_environment_context"):
                        now = datetime.datetime.now()
                        time_str = now.strftime("%A, %B %d, %Y at %I:%M %p")
                        env_context = f"[System context: It is currently {time_str}]\n"
                        formatted_input = env_context + formatted_input

                    await self.db.add_to_history(channel_id, "user", formatted_input)

                    # Start typing indicator
                    async def keep_typing_loop():
                        try:
                            while True:
                                async with channel.typing():
                                    await asyncio.sleep(8)
                        except asyncio.CancelledError:
                            pass
                    typing_task = asyncio.create_task(keep_typing_loop())

                    try:
                        # Generation Loop
                        history = await self.db.get_history(channel_id)
                        base_prompt = self.db.config.get("system_prompt", self.system_prompt_default)

                        if self.db.config.get("use_rag"):
                            rag_context = await self.rag_memory.search_context(channel_id, clean_input)
                            if rag_context:
                                base_prompt += f"\n\n[System note: Here is relevant past context you remember:]\n{rag_context}"

                        api_messages = [{"role": "system", "content": base_prompt}]
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
                        await self.db.add_to_history(channel_id, "assistant", bot_reply)
                        clean_reply = bot_reply.replace(f"[{self.target_user}]:", "").strip()

                        if self.db.config.get("use_rag"):
                            await self.rag_memory.add_interaction(channel_id, author_name, clean_input, clean_reply)

                        # GIF Reaction Logic (Checked before sending text)
                        sent_gif = False
                        try:
                            gif_mode = int(self.db.config.get("gif_mode", "0"))
                            if gif_mode > 0:
                                raw_triggers = self.db.config.get("gif_triggers", "i don't know,idk")
                                triggers = [t.strip().lower() for t in raw_triggers.split(",") if t.strip()]
                                reply_lower = clean_reply.lower()

                                matched_trigger = next((t for t in triggers if t in reply_lower), None)

                                if matched_trigger:
                                    gif_url = await self.fetch_reaction_gif(gif_mode, matched_trigger)
                                    if gif_url:
                                        await message.channel.send(gif_url)
                                        sent_gif = True
                        except Exception as gif_error:
                            print(f"Non-critical error processing GIF reaction: {gif_error}")

                        # Only send the generated text if a GIF was not sent
                        if not sent_gif:
                            await self.send_chunked_reply(message, clean_reply)

                        self.bot_stats["messages_processed"] += 1

                    except Exception as e:
                        self.bot_stats["errors"] += 1
                        await self.db.pop_last_history(channel_id)
                        await message.reply(f"Error: {e}")
                    finally:
                        typing_task.cancel()

                # Clean up processing state
                try:
                    await message.remove_reaction('👀', self.user)
                except discord.HTTPException:
                    pass

                await self.db.dequeue_message(message_id)

            except Exception as e:
                print(f"Queue worker critical error: {e}")

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

        if self.shutting_down:
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

        clean_input = message.content.replace(f'<@{self.user.id}>', '').replace(f'<@!{self.user.id}>', '').strip()
        if not clean_input and message.attachments:
            clean_input = "[Sent an attachment]"

        if not clean_input:
            return

        formatted_input = f"[{message.author.name}]: {clean_input}"

        if should_reply:
            try:
                await message.add_reaction('⏳')
            except discord.HTTPException:
                pass

            received_at = time.time()
            # Immediately save to persistent queue instead of locking here
            await self.db.enqueue_message(message.id, message.channel.id, message.author.name, clean_input, received_at)
            await self.generation_queue.put((message.id, message.channel.id, message.author.name, clean_input, received_at))

        elif should_track:
            await self.db.add_to_history(message.channel.id, "user", formatted_input)


def run_bot():
    bot = DiscordLLMBot()
    bot.run(bot.bot_token)
