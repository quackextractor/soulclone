import os
import sys
import time
import discord
import asyncio
from collections import deque
from discord.ext import commands
from openai import AsyncOpenAI
from dotenv import load_dotenv

def run_bot():
    # Load environment variables
    load_dotenv()

    target_user = os.getenv("TARGET_USER")
    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    base_url = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
    api_key = os.getenv("LM_STUDIO_API_KEY", "lm-studio")
    admin_user = os.getenv("ADMIN_USER")

    if not bot_token or not target_user:
        print("Error: DISCORD_BOT_TOKEN and TARGET_USER must be set in your .env file.")
        return
    
    if not admin_user:
        print("Warning: ADMIN_USER is not set in .env. Admin commands will be unusable.")

    # Dynamic configuration state
    bot_config = {
        "max_history": 10,
        "track_non_mentions": False,
        "enabled": False,               # Bot starts up disabled
        "reply_any_message": False,     # Any message mode
        "allowed_channel_id": None      # Channel restriction
    }

    # Use AsyncOpenAI to prevent blocking the Discord event loop
    client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    # Configure Discord bot intents
    intents = discord.Intents.default()
    intents.message_content = True
    
    bot = commands.Bot(command_prefix="!", intents=intents)

    # 1. Rate Limiting / Queue Setup
    request_lock = asyncio.Lock()

    # 2. Conversation Memory Setup
    channel_histories = {}
    
    # 3. Bot Statistics Tracking
    bot_stats = {
        "start_time": time.time(),
        "messages_processed": 0,
        "errors": 0
    }

    # --- ADMIN CHECK DECORATOR ---
    def is_admin():
        async def predicate(ctx):
            if ctx.author.name == admin_user:
                return True
            await ctx.send("You do not have permission to use this command.")
            return False
        return commands.check(predicate)

    @bot.event
    async def on_ready():
        print(f'Successfully logged in as {bot.user}')

    # --- UTILITY & ADMIN COMMANDS ---

    @bot.command(name="reset", help="Clears the conversation memory for the current channel.")
    async def reset_memory(ctx):
        if ctx.channel.id in channel_histories:
            channel_histories[ctx.channel.id].clear()
            channel_name = "DM" if isinstance(ctx.channel, discord.DMChannel) else f"#{ctx.channel.name}"
            await ctx.send(f"Memory wiped for {channel_name}. Starting fresh!")
        else:
            await ctx.send("There is no memory to clear for this channel.")

    @bot.command(name="stats", help="Shows bot performance and usage statistics.")
    async def show_stats(ctx):
        uptime_seconds = int(time.time() - bot_stats["start_time"])
        mins, secs = divmod(uptime_seconds, 60)
        hours, mins = divmod(mins, 60)
        uptime_str = f"{hours}h {mins}m {secs}s"
        
        memory_size = len(channel_histories.get(ctx.channel.id, []))
        
        embed = discord.Embed(title="Bot Statistics", color=discord.Color.blue())
        embed.add_field(name="Uptime", value=uptime_str, inline=False)
        embed.add_field(name="Messages Processed", value=str(bot_stats["messages_processed"]), inline=True)
        embed.add_field(name="Errors Encountered", value=str(bot_stats["errors"]), inline=True)
        embed.add_field(name="Current Channel Memory", value=f"{memory_size} / {bot_config['max_history']} messages", inline=False)
        
        await ctx.send(embed=embed)

    @bot.command(name="config", help="Displays the current bot configuration.")
    async def show_config(ctx):
        embed = discord.Embed(title="Bot Configuration", color=discord.Color.green())
        embed.add_field(name="Target User Persona", value=target_user, inline=False)
        embed.add_field(name="Admin User", value=admin_user or "None Set", inline=True)
        embed.add_field(name="Max History (Memory)", value=str(bot_config["max_history"]), inline=True)
        embed.add_field(name="Track Non-Mentions", value=str(bot_config["track_non_mentions"]), inline=True)
        embed.add_field(name="Bot Enabled", value=str(bot_config["enabled"]), inline=True)
        embed.add_field(name="Any Message Mode", value=str(bot_config["reply_any_message"]), inline=True)
        
        channel_name = "None (Any)"
        if bot_config["allowed_channel_id"]:
            channel = bot.get_channel(bot_config["allowed_channel_id"])
            if channel:
                channel_name = f"#{channel.name}"
            else:
                channel_name = str(bot_config["allowed_channel_id"])
        embed.add_field(name="Restricted Channel", value=channel_name, inline=True)
        
        embed.add_field(name="LLM Endpoint", value=base_url, inline=False)
        await ctx.send(embed=embed)

    @bot.command(name="set_history", help="[Admin] Set the maximum conversation history length.")
    @is_admin()
    async def set_history(ctx, length: int):
        if length < 1:
            await ctx.send("History length must be at least 1.")
            return
        
        bot_config["max_history"] = length
        
        # Resize existing memory buffers
        for channel_id, history in channel_histories.items():
            channel_histories[channel_id] = deque(history, maxlen=length)
            
        await ctx.send(f"`MAX_HISTORY` set to {length}. Existing histories truncated if necessary.")

    @bot.command(name="toggle_tracking", help="[Admin] Toggle tracking of non-mention messages in history.")
    @is_admin()
    async def toggle_tracking(ctx):
        bot_config["track_non_mentions"] = not bot_config["track_non_mentions"]
        state = "ON" if bot_config["track_non_mentions"] else "OFF"
        await ctx.send(f"Tracking of non-mention messages is now **{state}**.")

    @bot.command(name="toggle_bot", help="[Admin] Toggle whether the bot replies to messages.")
    @is_admin()
    async def toggle_bot(ctx):
        bot_config["enabled"] = not bot_config["enabled"]
        state = "ON" if bot_config["enabled"] else "OFF"
        await ctx.send(f"Bot answering is now **{state}**.")

    @bot.command(name="toggle_anymessage", help="[Admin] Toggle 'any message' mode (reply without mention).")
    @is_admin()
    async def toggle_anymessage(ctx):
        bot_config["reply_any_message"] = not bot_config["reply_any_message"]
        state = "ON" if bot_config["reply_any_message"] else "OFF"
        await ctx.send(f"Any message mode is now **{state}**.")

    @bot.command(name="set_channel", help="[Admin] Restricts bot replies to a specific channel. Use 'clear' to unrestrict.")
    @is_admin()
    async def set_channel(ctx, arg: str = None):
        if arg and arg.lower() == "clear":
            bot_config["allowed_channel_id"] = None
            await ctx.send("Channel restriction removed. The bot can now reply in any channel.")
        else:
            bot_config["allowed_channel_id"] = ctx.channel.id
            channel_name = "DM" if isinstance(ctx.channel, discord.DMChannel) else f"#{ctx.channel.name}"
            await ctx.send(f"Bot is now restricted to channel: {channel_name}")

    @bot.command(name="shutdown", help="[Admin] Completely shuts down the bot script.")
    @is_admin()
    async def shutdown(ctx):
        await ctx.send("Shutting down bot script...")
        await bot.close()
        sys.exit(0)

    @bot.command(name="restart", help="[Admin] Restarts the bot script.")
    @is_admin()
    async def restart(ctx):
        await ctx.send("Restarting bot script...")
        await bot.close()
        os.execv(sys.executable, ['python'] + sys.argv)

    @bot.command(name="ping", help="Checks the bot's response latency.")
    async def ping(ctx):
        latency_ms = round(bot.latency * 1000)
        await ctx.send(f"Pong! Latency: {latency_ms}ms")

    # --- MAIN MESSAGE EVENT ---

    @bot.event
    async def on_message(message):
        # Prevent the bot from replying to itself
        if message.author == bot.user:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)

        # Restrict DMs to the admin user only
        if is_dm and message.author.name != admin_user:
            return

        # Process commands first (like !reset, !stats). If it's a command, execute it and stop.
        if message.content.startswith(bot.command_prefix):
            await bot.process_commands(message)
            return

        # Check channel restriction (Allow admin DMs to bypass channel restrictions)
        if not is_dm and bot_config["allowed_channel_id"] is not None and message.channel.id != bot_config["allowed_channel_id"]:
            return

        is_mentioned = bot.user in message.mentions
        
        # Determine if the bot should physically reply. It must be enabled to reply.
        should_reply = (is_mentioned or bot_config["reply_any_message"] or is_dm) and bot_config["enabled"]
        
        # Determine if we should save the message to history. 
        # We save if we are going to reply, OR if passive tracking is turned on.
        should_save_history = should_reply or bot_config["track_non_mentions"]

        # Only process for history if we are replying OR if non-mention tracking is ON
        if should_save_history:
            
            # Clean the input by removing the bot mention from the text (supports both standard and nickname mentions)
            user_input = message.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()

            # Extract the sender's username and format it to match the training data
            sender_name = message.author.name
            formatted_user_input = f"[{sender_name}]: {user_input}"

            # Initialize channel history if it doesn't exist, using dynamic max_history
            if message.channel.id not in channel_histories:
                channel_histories[message.channel.id] = deque(maxlen=bot_config["max_history"])

            # Add the new user message to the memory buffer
            channel_histories[message.channel.id].append(
                {"role": "user", "content": formatted_user_input}
            )

        # Trigger the LLM only if we are set to reply
        if should_reply:
            async with message.channel.typing():
                try:
                    # Build the full prompt including the system instructions
                    api_messages = [{"role": "system", "content": f"You are {target_user} in a Discord chat."}]
                    
                    # Combine consecutive messages from the same role to prevent API errors in local models
                    for msg in channel_histories[message.channel.id]:
                        if api_messages[-1]["role"] == msg["role"]:
                            api_messages[-1]["content"] += f"\n{msg['content']}"
                        else:
                            # Append a new dictionary to avoid mutating the original history deque
                            api_messages.append({"role": msg["role"], "content": msg["content"]})

                    # Wait in line if the server is busy processing another request
                    async with request_lock:
                        # Send the combined history to your local model
                        response = await client.chat.completions.create(
                            model="local-model",
                            messages=api_messages
                        )

                    bot_reply = response.choices[0].message.content
                    
                    # Add the bot's response to the memory buffer so it remembers what it said
                    channel_histories[message.channel.id].append(
                        {"role": "assistant", "content": bot_reply}
                    )

                    # Strip the target user bracket tag if the model generates it
                    clean_reply = bot_reply.replace(f"[{target_user}]:", "").strip()

                    await message.reply(clean_reply)
                    
                    # Update stats
                    bot_stats["messages_processed"] += 1

                except Exception as e:
                    # If an error occurs, remove the failed user message from history to prevent bad state
                    if channel_histories[message.channel.id]:
                        channel_histories[message.channel.id].pop()
                        
                    bot_stats["errors"] += 1
                    await message.reply(f"Error communicating with local server: {e}")

    # Start the bot
    bot.run(bot_token)

if __name__ == "__main__":
    run_bot()