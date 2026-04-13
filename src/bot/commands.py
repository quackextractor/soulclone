"""
Discord bot commands and administrative controls.
Contains the primary Cog for user interactions and settings adjustments.
"""
import os
import sys
import time
import discord
from discord.ext import commands


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

    @commands.command(name="s", aliases=["stats", "st"], help="Shows bot stats. (;s)")
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
        # Bypassing the AttributeError safely if 'admin_user' string doesn't exist
        embed.add_field(name="Admin User", value=getattr(self.bot, 'admin_user', str(self.bot.admin_user_id)), inline=True)
        embed.add_field(name="Max History (Memory)", value=str(self.bot.db.config["max_history"]), inline=True)
        embed.add_field(name="Track Non-Mentions", value=str(self.bot.db.config["track_non_mentions"]), inline=True)
        embed.add_field(name="Bot Enabled", value=str(self.bot.db.config["enabled"]), inline=True)
        embed.add_field(name="Any Message Mode", value=str(self.bot.db.config["reply_any_message"]), inline=True)
        embed.add_field(name="Queue Expiration", value=f"{self.bot.db.config['queue_expiration']}s", inline=True)

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
            # Running as a bundled executable
            os.execv(sys.executable, sys.argv)
        else:
            # Running as a raw python script
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
        sys.exit(0)
