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