# Discord Soul Clone: Improved Implementation Plan

Below is the comprehensive, prioritized implementation plan for the Discord Soul Clone project. Tasks are ordered by immediate impact, stability, and logical progression, incorporating the optimized architectural strategies to prevent bottlenecks and hardware crashes.

### Phase 1: High Priority, Low Effort (Access Control & Core Status)

These tasks address immediate usability and access control limitations. They require minimal code changes and introduce no new dependencies.

* **DM Access Whitelist**
    * **Goal**: Add a separate configurable whitelist for people who can use the bot in DMs, moving away from the hardcoded `admin_user` check.
    * **Implementation**: Store the `dm_whitelist` in the SQLite `config` table. Create a new Discord command (e.g., `/whitelist add <user_id>`) that allows the admin to update this list dynamically, keeping it consistent with the rest of the bot's state management logic without requiring a reboot.

* **Bot Status Indicator**
    * **Goal**: Have the Discord presence show the bot status (e.g., disabled, enabled in server, or restricted to a specific channel).
    * **Implementation**: Implement a state-hashing or dirty-flag mechanism. The bot must only dispatch a `change_presence` API call if the newly calculated status string differs from the currently cached status string to strictly avoid Discord API rate limits.

* **Queue Expiration Time**
    * **Goal**: Add a configurable expiration time in seconds for queued messages.
    * **Implementation**: Record the exact timestamp when the message is received. Inside the execution lock, immediately calculate the time difference. If `current_time` minus `message_timestamp` is greater than `expiration_limit`, discard the generation request instantly. This prevents the LLM from wasting compute cycles on stale requests.

* **Laptop Hardware Testing**
    * **Goal**: Test on a low-end device to determine how the architecture will run on a standard laptop.
    * **Implementation**: Export the CPU-optimized Q4_K_M GGUF model artifact. Run the local inference logic using the CPU bindings provided by `llama.cpp` and log the tokens-per-second and RAM footprint metrics.

***

### Phase 2: High Priority, Medium to High Effort (Architecture Fixes & Safety)

These tasks solidify the bot's core functionality, ensure safety compliance, and modernize the Discord command structure.

* **Persistent Queue on Restart**
    * **Goal**: Make the queue persist on restart or reboot to ensure no pending responses are lost.
    * **Implementation**: Store only the bare minimum primitives in a new SQLite `message_queue` table (specifically `channel_id`, `message_id`, and `formatted_input`). On restart, the bot must use `await bot.fetch_channel()` and `await channel.fetch_message()` to reconstruct the necessary Discord objects before sending the queued prompt to the LLM lock.

* **Lightning-Fast Keyword Filter**
    * **Goal**: Add a high-performance safety layer to block or flag specific toxic or prohibited words before they are sent to Discord.
    * **Implementation**: Compile a standard Python regex pattern `re.compile(r'\b(word1|word2)\b', re.IGNORECASE)` during the bot's initialization. This operates in near O(N) time and requires zero external dependencies, making it perfectly suited for checking short Discord messages without over-engineering.

* **Migrate to Discord Slash Commands**
    * **Goal**: Migrate to regular Discord slash commands with ephemeral messages to reduce channel clutter.
    * **Implementation**: Refactor the `BotCommands` class to inherit from `app_commands.CommandTree` and convert text prefix commands. Crucially, implement a manual, admin-only synchronization command to sync the tree specifically to a test guild ID to bypass global propagation delays during the development cycle.

***

### Phase 3: Medium Priority, Medium Effort (Conversational Features & CI/CD)

These items enhance the personality and lifecycle management of the bot. They are prioritized lower because the core bot functions successfully without them.

* **Time & Environment Awareness**
    * **Goal**: Dynamically inject the current time, day, and weather data into the context.
    * **Implementation**: Do not alter the base system prompt to preserve KV-cache efficiency. Instead, inject the time awareness as a subtle, automated `user` role message right before the actual user's prompt (e.g., `[System context: It is currently 2:00 PM. User says:]: Hello!`).

* **Follow-Up Messages**
    * **Goal**: Allow the bot to make follow up messages if it replied short and no one wrote anything in a few seconds.
    * **Implementation**: Tie the follow-up logic strictly to the channel's latest message ID. After the configured sleep duration, fetch the channel's most recent message. If the ID matches the bot's last reply, it is safe to proceed. If the ID has changed, silently cancel the follow-up task to prevent race conditions.

* **Reactions and GIF Integration**
    * **Goal**: Add funny reaction commands and allow the bot to send a gif from a list of favorites.
    * **Implementation**: Create a local JSON mapping of categorized GIF URLs. Program the system prompt to allow the LLM to output specific action tags (e.g., `*sends a reaction*`). Parse the output string, strip the tag, and randomly select a corresponding URL from the JSON list to append to the message payload.

* **Automated Updates & CI/CD**
    * **Goal**: Add autoupdate from GitHub while protecting the active message queue.
    * **Implementation**: Create a designated `/update` application command. Set an internal state flag to block new messages from entering the active processing loop, routing them directly to the persistent queue instead. Wait for the `global_llm_lock` to clear, execute a `git pull` subprocess, and use `os.execv` to reboot the bot script automatically.

***

### Phase 4: Low Priority, High Effort (Advanced AI & Integrations)

These features introduce significant architectural complexity, external dependencies, and potential hardware bottlenecks.

* **Contextual Summarization**
    * **Goal**: Generate a one-sentence summary of dropped context to keep the conversation thread alive indefinitely instead of outright deleting old messages.
    * **Implementation**: Detect when the history hits the `max_history` capacity threshold. Extract the oldest messages targeted for deletion and send them to the local inference API on a background thread with a strict summarization prompt. Prepend the resulting summary string into the persistent system prompt.

* **Long-Term Memory (RAG)**
    * **Goal**: Implement a vector database to allow the bot to recall conversations from weeks ago.
    * **Implementation**: To prevent Out Of Memory crashes on consumer hardware, completely separate the text generation from the auxiliary tasks. Use ChromaDB with a CPU-optimized, ultra-lightweight model (like `all-MiniLM-L6-v2`) for embeddings to preserve local GPU VRAM strictly for the 3B personality clone.

* **Multimodal (Image/Meme) Support**
    * **Goal**: Integrate a vision model to generate text descriptions of uploaded images.
    * **Implementation**: Outsource vision multimodal support to an external API endpoint rather than running a model like LLaVA locally. Extract the generated text description and format it into the context stream.

* **Local Model Switching**
    * **Goal**: Implement commands to list available models, unload the existing model, and load a chosen model via the local API.
    * **Implementation**: Verify that the configured API backend (e.g., LM Studio) supports dynamic loading endpoints. Create `/model list` and `/model load` Discord commands to send the necessary HTTP POST requests to swap weights directly in the VRAM.