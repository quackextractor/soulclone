# Documentation & Run Guide

This document provides in-depth instructions on how to configure and execute each phase of the Discord Persona Pipeline.

---

## 1. Configuration Setup

Before running any scripts, you must configure your local environment and ruleset.

### `.env`
Create a `.env` file in the root directory (use `.env.example` as a template).
* `SOURCE_DIR`: The absolute path to the directory containing your exported Discord `.csv` files.
* `TARGET_USER`: The username (without the `#1234` discriminator) of the person you are cloning.
* `ZIP_PASSWORD`: A secure password. This is used by `sampler.py` to encrypt your final dataset, ensuring that sensitive chat logs cannot be intercepted if uploaded to cloud storage.

### `config.yaml`
This file controls the behavior of the data extraction logic.
* **`preprocessing`**:
    * `max_context_window`: How many previous messages to include as context for the model.
    * `max_time_delta_seconds`: If a message is sent this many seconds after the previous one, it breaks the context chain.
    * `language_detection_mode`: Set to `"C"` to actively inject hints like "Respond in German." into the system prompt.
* **`sampling`**:
    * `target_total_samples`: How many final conversations to extract for training (e.g., `1000`).
    * `response_distribution`: Allows you to mandate a specific percentage of short vs. long responses (e.g., force 40% of the dataset to be short responses to prevent the clone from writing unnatural paragraphs).

---

## 2. Preprocessing

**File:** `preprocess.py`

This script recursively scans the `SOURCE_DIR` for any `.csv` files. It builds an in-memory SQLite database to map Discord User IDs to readable usernames, reconstructs conversation threads based on timestamps, and filters out system messages and bot commands.

**How to run:**
Ensure `config.yaml` and `.env` are set, then execute this script as part of the main pipeline. It will output a massive `dataset.jsonl` file containing all valid conversation pairs.

---

## 3. Sampling & Encryption

**File:** `sampler.py`

This script reads the raw `dataset.jsonl` and randomly samples it down to your `target_total_samples` limit while enforcing your desired sentence-length distribution. 

Once sampled, it uses AES-256 to securely zip the final `samples.jsonl` and the metadata report into `processed_samples.zip` using your `.env` password.

**How to run:**
Execute this script. Take the resulting `processed_samples.zip` and upload it to your Google Drive.

---

## 4. Fine-Tuning (Google Colab)

**File:** `clone-training.ipynb`

This notebook uses the highly-optimized Unsloth library to train a QLoRA adapter on top of the Hermes 3 (3B) base model using a free Colab T4 GPU. 

**How to run:**
1. Upload `processed_samples.zip` to Google Drive and generate a shared link.
2. Open `clone-training.ipynb` in Google Colab.
3. In the first configuration cell, paste your `GDRIVE_SHARED_LINK` and your `DECRYPTION_KEY` (the `ZIP_PASSWORD` you used).
4. Enter your `ENCRYPTION_KEY`. This ensures the resulting model adapter and GGUF weights are encrypted when saved.
5. Run all cells (`Runtime -> Run All`).

**Expected Output:**
* An Unsloth-optimized QLoRA adapter zipped and encrypted as `final_adapter_encrypted.zip` saved straight to your Google Drive.
* A CPU-optimized GGUF version (Q4_K_M) zipped and encrypted as `cpu_model_gguf_encrypted.zip` saved straight to your Google Drive.

---

## 5. Live Inference & Chat (Google Colab)

**File:** `chat-inference.ipynb`

This notebook allows you to talk to your freshly trained persona in real time. It utilizes native C-optimized stop strings to prevent the model from impersonating the user, and uses a threaded streamer to yield tokens to the screen instantly.

**Key Features:**
* **Universal Loader:** Natively supports loading both encrypted LoRA adapter zip files OR encrypted GGUF zip files.
* **Deep Memory:** Retains up to 6,000 tokens of conversation history (highly optimized for the 3B model).
* **Group Chat Simulation:** Seamlessly swap user identities mid-conversation without dropping context.

**How to run:**
1. Open `chat-inference.ipynb` in Google Colab.
2. Fill out the configuration block with the `GDRIVE_SHARED_LINK` pointing to your encrypted payload (adapter or GGUF) and the `DECRYPTION_KEY`.
3. Set the `CLONE_NAME` to match your target.
4. Run all cells.

**In-Chat Commands:**
Once the terminal starts, you can use these commands on the fly:
* `quit` / `exit` / `stop` - End the chat.
* `reset` - Clear memory and change the starting user.
* `/user <name>` - Switch your username seamlessly to simulate a group chat context without wiping memory.
* `/strict` - Toggle anti-hallucination stop strings on/off (`\n[`).
* `/config` - View current model parameters, clone name, and system prompt.
* `/stats` - View session lengths, memory usage, and message counts.
* `/temp <value>` - Adjust hallucination temperature dynamically (e.g., `/temp 0.8`).
* `/pen <value>` - Adjust repetition penalty dynamically (e.g., `/pen 1.15`).
* `/undo` - Remove the last message exchange (pops the last user-assistant pair to perfectly maintain ChatML structure).
* `/benchmark` - Run stored prompts and save outputs to Drive.
* `/benchmark <filepath>` - Import benchmarks from a text file.
* `/benchmark --reset` - Wipe stored custom benchmarks.
* `/switch <gdrive_link> [password]` - Hot-swap the persona adapter or GGUF natively.

---

## 6. Operational Notes & Known Edge Cases

**1. The GGUF De-Quantization Trap (Hardware Limit)**
While the inference notebook features a universal loader that can ingest `.gguf` files, doing so natively inside the Hugging Face / Unsloth ecosystem de-quantizes the model back into 16-bit float in the GPU memory. 
* For a 3B model, this takes about 6GB to 7GB VRAM, which fits easily on a free Colab T4.
* If you attempt to load a 12B+ GGUF model this way, it will expand to 24GB+ VRAM and instantly crash the notebook with an Out Of Memory (OOM) error. 
* **Best Practice:** Stick to loading the LoRA Adapter + Base Model inside Colab, and save the compressed GGUF files exclusively for your final Discord bot running on `llama.cpp`.

**2. Stop-String Visual Leakage (UI Glitch)**
Because the `TextIteratorStreamer` runs on a separate background thread, it aggressively yields tokens to the screen to simulate live typing. When the model attempts to hallucinate a bracketed username, the GPU stops generation instantly. However, the streamer might have already flashed the `\n` and `[` onto your screen before the stop command successfully terminated the thread. The internal memory remains completely clean, but you may occasionally see the bot type a bracket and then freeze in the Colab UI.

**3. The List Cut-Off (Stop-String Trade-Off)**
To rigidly prevent the model from roleplaying as other users, the hardware stop string is set to `\n[`. If your clone ever attempts to write a cleanly formatted markdown list (e.g., `\n[1] First item`), the exact millisecond the GPU generates that bracket, the inference engine will forcefully abort. This is a highly acceptable trade-off to completely eliminate group-chat hallucinations, but it explains why the bot might occasionally cut off mid-sentence if it tries to list things.