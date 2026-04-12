# Discord Soul Clone - Project TODO

### Core Architecture & Deployment
* [ ] **How will this run on a laptop?** Test on a low-end device.
* [x] **How does the bot handle DMs/multiple servers? Do separate channels have separate histories?** (Note: Yes, the bot's SQLite `history` table tracks conversational memory strictly by `channel_id`. When it pulls past context, it filters specifically for the current channel, so every DM and server channel maintains a isolated history.)
* [ ] **Long-Term Memory (RAG):** Implement a vector database (e.g., ChromaDB or FAISS) to allow the bot to recall conversations from weeks ago. When a user asks about something from the past, the bot will fetch the relevant embedded context and inject it into the system prompt.

---

### Access Control & Model Management
* [ ] **Lightning-fast keyword filter:** Add a high-performance safety layer to block or flag specific toxic or prohibited words before they are sent to Discord to ensure the uncensored model remains compliant with server rules.
* [ ] **Add a separate configurable whitelist for people who can use bot in DMs.** (Note: Currently, the bot has a hardcoded check that only allows the designated `admin_user` in the `.env` to interact with it via DM.)
* [ ] **Add model switching:** Implement commands to list available models, unload the existing model, and load a chosen model via the local API.

---

### Bot Persona & Conversational Features
* [ ] **Time & Environment Awareness:** Dynamically inject the current time, day, and weather/environment data into the system prompt (e.g., `[System: It is currently 2:00 AM on a Tuesday]`) so the clone can naturally reference being tired or talk about the weekend.
* [ ] **Multimodal (Image/Meme) Support:** Integrate a local vision model (e.g., LLaVA) to generate a brief text description of uploaded images or memes. This description is fed to the clone (e.g., `[User sent an image of a cat on a skateboard]`) so it can "see" and react to visual content.
* [ ] **Allow the bot to make follow up messages** if it replied short and no one wrote anything in a few seconds. (Fully configurable amount of words and time in seconds).
* [ ] **Add funny "react to this" commands** and other personality-driven interactions.
* [ ] **Allow the bot to send a gif from a large list of favorites to react** (e.g., referencing "lustsouls huge list").

---

### State Management & Task Queue
* [ ] **Contextual Summarization:** Instead of outright deleting the oldest messages when hitting the `max_history` limit, have the bot generate a one-sentence summary of the dropped context to keep the "thread" of the conversation alive indefinitely.
* [ ] **Make the queue persist on restart / reboot** to ensure no pending responses are lost.
* [ ] **Add configurable expiration time in seconds.** If a message in the queue expires, remove the hourglass reaction and add an "expired" emoji.

---

### Discord Integration & UI
* [ ] **Consider migration to regular Discord "/" commands** with ephemeral messages (messages only visible to the user) to reduce channel clutter.
* [ ] **Have status show the bot status** (e.g., disabled, enabled in server, or enabled specifically in a #channel).

---

### Development, CI/CD, & Releases
* [x] **Add precommit hooks** with unit tests and linting + autofix linting to maintain code quality.
* [ ] **Add autoupdate from GitHub:** Finish writing currently queued messages before the update is received. Any messages queued after the update should be scheduled for after the restart. The bot should announce it is "restarting for update" (using `git pull`) and then resume the persistent queue.
* [x] **Add releases:** Generate binary versions for Windows and Linux on changelog version bumps (following the workflow used in previous projects like `textfilemerger`).
* [ ] **For non-dev versions, add configurable auto-download and install of new releases** instead of requiring a manual `git pull`.