import os
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

    if not bot_token or not target_user:
        print("Error: DISCORD_BOT_TOKEN and TARGET_USER must be set in your .env file.")
        return

    # Use AsyncOpenAI to prevent blocking the Discord event loop
    client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    # Configure Discord bot intents
    intents = discord.Intents.default()
    intents.message_content = True
    
    # Upgraded to commands.Bot to easily support utility commands alongside the LLM mentions
    bot = commands.Bot(command_prefix="!", intents=intents)

    # 1. Rate Limiting / Queue Setup
    request_lock = asyncio.Lock()

    # 2. Conversation Memory Setup
    MAX_HISTORY = 10 
    channel_histories = {}
    
    # 3. Bot Statistics Tracking
    bot_stats = {
        "start_time": time.time(),
        "messages_processed": 0,
        "errors": 0
    }

    @bot.event
    async def on_ready():
        print(f'Successfully logged in as {bot.user}')

    # --- UTILITY COMMANDS ---

    @bot.command(name="reset", help="Clears the conversation memory for the current channel.")
    async def reset_memory(ctx):
        if ctx.channel.id in channel_histories:
            channel_histories[ctx.channel.id].clear()
            await ctx.send(f"🧠 Memory wiped for #{ctx.channel.name}. Starting fresh!")
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
        embed.add_field(name="Current Channel Memory", value=f"{memory_size} / {MAX_HISTORY} messages", inline=False)
        
        await ctx.send(embed=embed)

    @bot.command(name="config", help="Displays the current bot configuration.")
    async def show_config(ctx):
        embed = discord.Embed(title="Bot Configuration", color=discord.Color.green())
        embed.add_field(name="Target User Persona", value=target_user, inline=False)
        embed.add_field(name="Max History (Memory)", value=str(MAX_HISTORY), inline=True)
        embed.add_field(name="LLM Endpoint", value=base_url, inline=False)
        await ctx.send(embed=embed)

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

        # Process commands first (like !reset, !stats). If it's a command, execute it and stop.
        if message.content.startswith(bot.command_prefix):
            await bot.process_commands(message)
            return

        # Trigger the bot only if it is mentioned
        if bot.user in message.mentions:
            # Clean the input by removing the bot mention from the text
            user_input = message.content.replace(f'<@{bot.user.id}>', '').strip()

            # Extract the sender's username and format it to match the training data
            sender_name = message.author.name
            formatted_user_input = f"[{sender_name}]: {user_input}"

            # Initialize channel history if it doesn't exist
            if message.channel.id not in channel_histories:
                channel_histories[message.channel.id] = deque(maxlen=MAX_HISTORY)

            # Add the new user message to the memory buffer
            channel_histories[message.channel.id].append(
                {"role": "user", "content": formatted_user_input}
            )

            # Send a typing indicator while the model generates the response
            async with message.channel.typing():
                try:
                    # Build the full prompt including the system instructions and history
                    api_messages = [{"role": "system", "content": f"You are {target_user} in a Discord chat."}]
                    api_messages.extend(list(channel_histories[message.channel.id]))

                    # Wait in line if the server is busy processing another request
                    async with request_lock:
                        # Send the history to your local model
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
                    # If an error occurs, remove the failed message from history to prevent bad state
                    if channel_histories[message.channel.id]:
                        channel_histories[message.channel.id].pop()
                        
                    bot_stats["errors"] += 1
                    await message.reply(f"Error communicating with local server: {e}")

    # Start the bot
    bot.run(bot_token)

if __name__ == "__main__":
    run_bot()