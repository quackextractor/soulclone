Here is your TODO list logically organized into functional sections. I've also added a few brief insights based on the existing `quackextractor-soulclone` codebase to help you cross off or clarify some of these items right away.

### Core Architecture & Deployment

* **How will this run on a laptop?** (Note: The pipeline natively exports a CPU-optimized GGUF (Q4_K_M) model designed specifically for local inference tools like LM Studio or Ollama. The current `discord_bot.py` is configured to connect to `http://localhost:1234/v1`, allowing it to run smoothly on a local machine alongside LM Studio.)
* **How does the bot handle DMs/multiple servers? Do separate channels have separate histories?** (Note: Yes, the bot's SQLite `history` table tracks conversational memory strictly by `channel_id`. When it pulls past context, it filters specifically for the current channel, so every DM and server channel maintains a completely isolated history.)

---

### Access Control & Model Management

* Add a separate configurable whitelist for ppl who can use bot in DMs (Note: Currently, the bot has a hardcoded check that only allows the designated `admin_user` to interact with it via DM.)
* Add model switching (list available models, unload existing, load chosen model).

---

### Bot Persona & Conversational Features

* Allow the bot to make follow up messages if it replied short and no one wrote anything in a few seconds. (Fully configurable amount of words, time in seconds).
* Add funny 'react to this' commands, etc.
* Allow the bot to send a gif from lustsouls huge list of favorites to react.

---

### State Management & Task Queue

* Make the queue persist on restart / reboot.
* Add configurable expiration time in seconds. If expired, remove hourglass and add an expired emoji.

---

### Discord Integration & UI

* Consider migration to regular discord '/' commands with messages only visible to you, etc.
* Have status show the bot status (disabled, enabled in server, enabled in #channel).

---

### Development, CI/CD, & Releases

* Add precommit with unit tests and linting+autofix lint.
* Add autoupdate from GitHub. Finish writing current queued messages before update was received (any queued messages after update was received are scheduled after restart), write that the bot is restarting for update (git pull for now) and then finish queue as queue is persistent.
* Add releases (Binary version for windows and Linux on changelog version bump (as was done with textfilemerger, etc).
* For non-dev versions add configurable auto download and install of new releases instead of git pull.