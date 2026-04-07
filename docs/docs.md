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
    * `target_total_samples`: How many final conversations to extract for training (e.g., `100`).
    * `response_distribution`: Allows you to mandate a specific percentage of short vs. long responses (e.g., force 40% of the dataset to be short responses to prevent the LLM from becoming overly verbose).

---

## 2. Preprocessing Data

**File:** `preprocess.py`

This script handles the heavy lifting of parsing gigabytes of raw Discord logs. It utilizes an in-memory SQLite database via Pandas to rapidly map numerical user pings (`<@123456789>`) back to readable usernames.

**How to run:** Ensure your virtual environment is active (via `setup.bat` ), then run:
```bash
python preprocess.py
```

**Expected Output:**
* Parses all CSVs in `SOURCE_DIR`.
* Outputs a large `processed/dataset.jsonl` containing every valid conversational pair.
* Outputs `processed/summary.json` with global statistics on dropped messages, kept data, and detected languages.

---

## 3. Sampling & Encryption

**File:** `sampler.py`

Training on raw chat logs often ruins LLMs because users naturally send a disproportionate amount of one-word replies like "yeah" or "lol". This script uses byte-offset reservoir scanning to sample the massive `dataset.jsonl` without crashing your RAM. It balances minority languages and strictly enforces the word-count distributions defined in `config.yaml`.

**How to run:**
```bash
python sampler.py
```

**Expected Output:**
* Generates `processed/samples.jsonl`.
* Creates `processed/sample_summary.json` showing exactly who the model is talking to in the sample and the breakdown of lengths.
* **Crucially:** Outputs `processed/processed_samples.zip`, fully encrypted with AES-256 using the password from your `.env`. This zip is what you upload to Google Drive for the Colab notebooks.

---

## 4. Model Training (Google Colab)

**File:** `clone-training.ipynb`

This notebook uses **Unsloth** to shrink the Mistral NeMo 12B model down into 4-bit quantization, allowing it to fit natively on a free Google Colab T4 GPU. It is configured for a single, aggressive epoch to prevent catastrophic forgetting while rapidly absorbing the persona.

**How to run:**
1. Upload your `processed_samples.zip` to Google Drive or obtain a direct shareable link.
2. Open `clone-training.ipynb` in Google Colab.
3. In the first configuration cell, paste your `GDRIVE_SHARED_LINK` and your `DECRYPTION_KEY` (the `ZIP_PASSWORD` you used).
4. Enter your `ENCRYPTION_KEY`. This ensures the resulting model adapter weights are encrypted when saved.
5. Run all cells (`Runtime -> Run All`).

**Expected Output:**
* An Unsloth-optimized QLoRA adapter zipped and encrypted as `final_adapter_encrypted.zip` saved straight to your Google Drive.

---

## 5. Live Inference & Chat (Google Colab)

**File:** `chat-inference.ipynb`

This notebook allows you to talk to your freshly trained persona in real time. It utilizes native C-optimized stop strings to prevent the model from impersonating the user, and uses a threaded streamer to yield tokens to the screen instantly.

**How to run:**
1. Open `chat-inference.ipynb` in Google Colab.
2. Fill out the configuration block with the `GDRIVE_SHARED_LINK` pointing to your `final_adapter_encrypted.zip` and the `DECRYPTION_KEY`.
3. Set the `CLONE_NAME` to match your target.
4. Run all cells.

**In-Chat Commands:**
Once the terminal starts, you can use these commands on the fly:
* `/temp 0.8` - Adjust hallucination temperature dynamically.
* `/pen 1.15` - Adjust repetition penalty dynamically.
* `/switch <gdrive_link> [password]` - Hot-swap the persona adapter without reloading the base 12B model.
* `/benchmark` - Run the LLM through a suite of stored custom questions and automatically save the dialogue logs to your Google Drive.