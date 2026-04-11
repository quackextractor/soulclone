# Changelog

All notable changes to the Discord Persona Cloning project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com), and this project adheres to [Semantic Versioning](https://semver.org/).

## [2.1.0] - 2026-04-11

### Added
* Added the `force_balanced` flag to `config.yaml` and integrated a strict bottleneck calculation within `sampler.py` to enforce the requested response distribution ratios, preventing minority buckets from breaking the output dataset balance.

## [2.0.0] - 2026-04-11

### Added
* Integrated support for `NousResearch/Hermes-3-Llama-3.2-3B` as the primary base model for training and inference to leverage its ChatML format and uncensored steerability (`7f94889`).
* Added a Universal GGUF and LoRA Adapter loader within `chat-inference.ipynb` using Python's `os.walk` to recursively scan and auto-detect model payloads without rigid paths (`7b6cfab`).
* Implemented the "Pre-fill Trick" which inherently injects the `[{CLONE_NAME}]: ` format directly into the tokenized prompt before generation, safely bypassing UI regex glitches (`8da72fe`).
* Created the `/user <name>` command to seamlessly swap user identities and simulate a group chat context without dropping the active conversation history (`8da72fe`).
* Added extensible diagnostic commands including `/stats` for viewing session memory usage and `/config` for viewing real-time generation parameters (`8da72fe`).

### Changed
* Expanded the sliding window memory capacity massively from 500 tokens to 6,000 tokens, leveraging the lightweight VRAM footprint of the 3B parameter model (`8da72fe`).
* Stripped dynamic language hints from the inference system prompt, as the Hermes 3 architecture natively tracks multi-lingual conversational flow, which prevents translation ping-pong degradation (`7f94889`).

### Fixed
* Fixed the "ChatML Alternating Role Crash" within the memory manager and `/undo` command by enforcing strict user-assistant pair popping to structurally preserve template sequence integrity (`12a2fcb`).

## [1.3.0] - 2026-04-09

### Added
* Developed a CPU-optimized GGUF (Q4_K_M) export phase designed for local inference tools like LM Studio and Ollama, appended directly to the Unsloth training loop (`9f2c5e4`).
* Implemented a high-speed local NVMe SSD export to temporarily bypass Google Drive network bottlenecks before safely transferring the final model artifacts (`9f2c5e4`).
* Injected native hardware stop strings (e.g., `\n[`) directly into the generation engine `kwargs` to physically halt the GPU instantly and prevent the model from roleplaying as the user (`a3901f3`).

### Fixed
* Resolved a critical 0-byte ZIP corruption error caused by `ZIP_STORED` clashing with AES-256 encryption limits by switching compression to `pyzipper.ZIP_DEFLATED` with `allowZip64=True` (`4299df0`).
* Substituted the generic Hugging Face `DataCollatorForCompletionOnlyLM` with a highly resilient `CustomCompletionCollator` that successfully targets `<|im_start|>assistant\n` to mask multi-turn user prompts (`cb3c8d5`).
* Fixed runtime crashes within the Unsloth library's `tqdm` progress bar by implementing a `__getattr__` passthrough for the custom `TeeOutput` system logger (`24b1e3e`).

## [1.2.0] - 2026-04-07

### Added
* Introduced Two-Pass Byte-Offset Reservoir Sampling within `sampler.py` utilizing `f.tell()` and `f.seek()` to fully eliminate Out-Of-Memory RAM crashes on massive JSONL datasets (`f66f8ed`).
* Added a comprehensive `/benchmark` suite to automatically run predefined, standardized prompts from specific Discord users and append chronological text logs to Google Drive for A/B testing (`f84f0b0`).
* Implemented multi-dimensional stratified language bucket sorting (English, German, Czech, Unknown) directly within the sampling sequence (`8978e4a`, `117ed09`).

### Changed
* Upgraded language detection in preprocessing from the sluggish `langdetect` library to `lingua-language-detector` for high-speed, pure-Python classification (`ed877ce`).
* Lowered `min_words_for_language_detect` to 3 tokens to prevent short, valid foreign phrases from incorrectly falling into the Unknown sorting bucket (`117ed09`).

### Fixed
* Resolved a massive SQL bottleneck during mention resolution (`<@12345>`) by dumping the in-memory SQLite mapping directly to a lightning-fast Python RAM dictionary (`USER_ID_MAP_RAM`) for O(1) lookups (`f66f8ed`, `0f2023c`).
* Prevented preprocessing context poisoning by explicitly dropping continuous placeholder spam (`[Attachment]`, `[Link]`) via a targeted regex pipeline (`52504fb`).

## [1.1.0] - 2026-04-06

### Added
* Created a standalone, state-aware `chat-inference.ipynb` simulator notebook to isolate real-time chat testing from the heavy training loops (`5bce5ef`).
* Built the `/switch` command to natively hot-swap encrypted persona adapters mid-conversation without needing to restart the Colab runtime (`e70b6f5`).
* Deployed real-time conversational inference utilizing `TextIteratorStreamer` running on a background GPU thread to stream output instantly (`8621b13`).
* Added adjustable `/temp` and `/pen` slash commands to control the inference engine's creativity and repetitiveness on the fly (`95c3e16`).
* Applied symmetrical target response formatting (`[{TARGET_USER}]: response`) in `preprocess.py` to establish strict conversational boundaries and halt hallucinated replies (`021b6be`).

### Changed
* Enforced a 40/40/20 length distribution (short/medium/long) via a multi-dimensional stratified sampling engine to prevent "soap opera" verbosity (`8978e4a`).
* Expanded `MAX_HISTORY_MESSAGES` to strictly enforce a sliding window multi-turn memory approach (`a4d1179`).

## [1.0.1] - 2026-04-05

### Added
* Integrated the Unsloth backend to leverage custom Triton kernels, achieving 2x faster fine-tuning and a 50% reduction in VRAM consumption (`794e307`).

### Fixed
* Mitigated `NotImplementedError` PyTorch crashes on Colab Turing architecture (T4) GPUs by forcing float32 upcasts for LoRA layers and overriding base model configurations to float16 (`dcc2137`).
* Bypassed a known Mistral tokenizer regex bug by explicitly overriding the Rust-based fast tokenizer using the `use_fast=False` parameter (`3304859`).

## [1.0.0] - 2026-04-04

### Added
* Created the initial Discord Persona fine-tuning architecture built entirely around the Mistral NeMo 12B model (`d577862`).
* Developed the base preprocessing engine (`preprocess.py`) to convert raw CSV Discord history into conversational token pairs (`afd6ecc`).
* Configured a robust QLoRA 4-bit (NF4) quantization setup alongside Gradient Checkpointing and Paged 8-bit AdamW optimizations to accommodate 12B parameters within 15GB of Colab VRAM (`50ca443`).
* Enforced the `min_context_window: 4` parameter to reject orphaned snippets, natively forcing the attention mechanism to learn deep conversational flow (`b4816c4`).
* Integrated built-in AES-256 encryption using the `pyzipper` library to strictly protect personal Discord datasets and adapter weights during all Google Drive transfers (`14581dc`).