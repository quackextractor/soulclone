# Discord Persona Fine-Tuning

## Overview
This project provides a data preprocessing pipeline designed to fine-tune a Large Language Model (LLM) to clone the conversational style, timing, and behavioral patterns of any specific target Discord user. By using exported CSV chat logs from direct messages, group chats, and server channels, this tool converts raw Discord history into a token-safe JSONL dataset ready for model training.

A core feature of the resulting dataset is authenticity: the tool preserves the user's habit of occasionally interrupting ongoing conversations to change the topic or request voice chats, assuming that is present in their historical data.

## Technical Stack
* **Environment:** Designed for fine-tuning via Google Colab (T4 GPU).
* **Training Method:** QLoRA (Low Rank Adaptation) with 4-bit quantization.
* **Expected Base Models:** Quantized models such as Llama-3-8B or Mistral-7B.
* **Libraries:** Hugging Face `transformers`, `datasets`, `peft`, `trl`, and `bitsandbytes`.

## Setup Instructions
1. Ensure you have Python 3.8+ installed.
2. Run the included setup script to generate your virtual environment and install dependencies:
   ```bat
   setup.bat
   ```
   *(Alternatively, manually create a `.venv`, activate it, and run `pip install -r requirements.txt`)*
3. Copy `.env.example` to a new file named `.env` and update `SOURCE_DIR` to point to your Discord chat CSV exports.
4. **Crucial:** Open `config.yaml` and update the `target_user` field to match the exact Discord username you want to clone. You can also adjust context window sizes, placeholder tags, and sampling limits here.

## Usage
The unified CLI tool `main.py` serves as the primary entry point. 

**Available Commands:**
* `python main.py preprocess` - Process raw Discord CSV exports into a fine-tuning dataset JSONL file.
* `python main.py sample` - Extract a small, token-safe JSONL sample from source files for debugging.

You can also run `python main.py preprocess --sample` to immediately generate samples right after building the main dataset.