"""
Database management module for the Discord bot.
Handles all SQLite operations, persistent memory, and dynamic configurations.
"""
import aiosqlite


class BotDatabase:
    def __init__(self, db_path: str, system_prompt_default: str):
        self.db_path = db_path
        self.system_prompt_default = system_prompt_default
        self.config = {}

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute('''CREATE TABLE IF NOT EXISTS config
                            (key TEXT PRIMARY KEY, value TEXT)''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS history
                            (channel_id INTEGER, role TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS dm_whitelist
                            (user_id INTEGER PRIMARY KEY)''')
            # Persistent queue table
            await conn.execute('''CREATE TABLE IF NOT EXISTS message_queue
                              (message_id INTEGER PRIMARY KEY, channel_id INTEGER,
                               author_name TEXT, clean_input TEXT, received_at REAL)''')
            await conn.commit()

    async def enqueue_message(self, message_id, channel_id, author_name, clean_input, received_at):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR REPLACE INTO message_queue VALUES (?, ?, ?, ?, ?)",
                               (message_id, channel_id, author_name, clean_input, received_at))
            await conn.commit()

    async def dequeue_message(self, message_id):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM message_queue WHERE message_id = ?", (message_id,))
            await conn.commit()

    async def get_queued_messages(self):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT message_id, channel_id, author_name, clean_input, received_at FROM message_queue ORDER BY received_at ASC") as cursor:
                return await cursor.fetchall()

    async def load_config(self):
        defaults = {
            "max_history": "15",
            "track_non_mentions": "False",
            "enabled": "False",
            "reply_any_message": "False",
            "allowed_channel_id": "None",
            "system_prompt": self.system_prompt_default,
            "restart_channel_id": "None",
            "queue_expiration": "60",
            "use_rag": "False",
            "use_environment_context": "False",
            "gif_mode": "0",
            "gif_triggers": "i don't know,i dont know,idk,no idea,im not sure"
        }

        async with aiosqlite.connect(self.db_path) as conn:
            for key, default in defaults.items():
                async with conn.execute("SELECT value FROM config WHERE key = ?", (key,)) as cursor:
                    row = await cursor.fetchone()
                    val_str = row[0] if row else default

                    if not row:
                        await conn.execute("INSERT INTO config (key, value) VALUES (?, ?)", (key, default))

                if val_str in ("True", "False"):
                    self.config[key] = (val_str == "True")
                elif key == "max_history":
                    self.config[key] = int(val_str)
                elif key in ("allowed_channel_id", "restart_channel_id"):
                    self.config[key] = int(val_str) if val_str != "None" else None
                elif key == "queue_expiration":
                    self.config[key] = int(val_str)
                else:
                    self.config[key] = val_str
            await conn.commit()

    async def update_config(self, key, value):
        self.config[key] = value
        val_str = str(value) if value is not None else "None"
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("UPDATE config SET value = ? WHERE key = ?", (val_str, key))
            await conn.commit()

    async def reset_to_defaults(self):
        defaults = {
            "max_history": "15",
            "track_non_mentions": "False",
            "enabled": "False",
            "reply_any_message": "False",
            "allowed_channel_id": "None",
            "system_prompt": self.system_prompt_default,
            "restart_channel_id": "None",
            "queue_expiration": "60",
            "use_rag": "False",
            "use_environment_context": "False",
            "gif_mode": "0",
            "gif_triggers": "i don't know,i dont know,idk,no idea,im not sure"
        }
        async with aiosqlite.connect(self.db_path) as conn:
            for key, default in defaults.items():
                await conn.execute("UPDATE config SET value = ? WHERE key = ?", (default, key))

                if default in ("True", "False"):
                    self.config[key] = (default == "True")
                elif key == "max_history":
                    self.config[key] = int(default)
                elif key in ("allowed_channel_id", "restart_channel_id"):
                    self.config[key] = None
                else:
                    self.config[key] = default
            await conn.commit()

    async def get_history(self, channel_id):
        max_h = self.config.get("max_history", 15)
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("""SELECT role, content FROM (
                                SELECT role, content, timestamp FROM history
                                WHERE channel_id = ? ORDER BY timestamp DESC LIMIT ?
                              ) ORDER BY timestamp ASC""", (channel_id, max_h)) as cursor:
                return [{"role": row[0], "content": row[1]} for row in await cursor.fetchall()]

    async def add_to_history(self, channel_id, role, content):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT INTO history (channel_id, role, content) VALUES (?, ?, ?)",
                               (channel_id, role, content))
            await conn.commit()

    async def pop_last_history(self, channel_id):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM history WHERE rowid = (SELECT MAX(rowid) FROM history WHERE channel_id = ?)", (channel_id,))
            await conn.commit()

    async def clear_history(self, channel_id):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM history WHERE channel_id = ?", (channel_id,))
            await conn.commit()

    async def is_whitelisted(self, user_id):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT 1 FROM dm_whitelist WHERE user_id = ?", (user_id,)) as cursor:
                return await cursor.fetchone() is not None

    async def add_whitelist(self, user_id):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("INSERT OR IGNORE INTO dm_whitelist (user_id) VALUES (?)", (user_id,))
            await conn.commit()

    async def remove_whitelist(self, user_id):
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("DELETE FROM dm_whitelist WHERE user_id = ?", (user_id,))
            await conn.commit()

    async def get_whitelist(self):
        async with aiosqlite.connect(self.db_path) as conn:
            async with conn.execute("SELECT user_id FROM dm_whitelist") as cursor:
                return [row[0] for row in await cursor.fetchall()]
