# Project Documentation: lustsoul Discord Persona Fine Tuning

## 1. Project Overview
This document serves as the comprehensive guide and historical log for the project aimed at fine tuning a Large Language Model (LLM). The primary objective is to clone the conversational style, timing, and behavioral patterns of the Discord user "lustsoul" using exported CSV chat logs from direct messages, group chats, and server channels.

## 2. Core Decisions and Methodology
A key behavioral pattern was identified during the initial data review: the target persona frequently interrupts ongoing conversations to introduce new topics or request voice chats.

**Strategic Decision: Option 1 (Authenticity)**
* The project will proceed with preserving the raw context of these interruptions in the training data rather than filtering them out.
* The resulting model will prioritize acting exactly like the user, which includes ignoring the current topic to ask for voice chats or send unrelated messages when the chat environment matches those historical conditions.

**Technical Stack:**
* **Environment:** Google Colab (T4 GPU)
* **Training Method:** QLoRA (Low Rank Adaptation) with 4 bit quantization
* **Libraries:** Hugging Face `transformers`, `datasets`, `peft`, `trl`, and `bitsandbytes`
* **Data Format:** JSONL (Context pairs consisting of 3 to 5 previous messages followed by the target "lustsoul" response)

***

## 3. Interaction Log

### 3.1. Interaction 1: Initial Setup

**User Prompt:**
The user requested instructions on how to fine tune an LLM in Google Colab to mimic the "lustsoul" persona using thousands of CSV entries. A sample of the provided Direct Messages CSV included:
* Headers for AuthorID, Author, Date, Content, Attachments, and Reactions.
* A message from "lustsoul" stating they could not find something on their phone and would send it later.
* A reply from "hiracan." saying "no problem".
* A subsequent message from "lustsoul" containing a link and the following reactions: `:flushed:` (1), `:hugging:` (1), `:handshake:` (1).

**Assistant Response:**
The assistant provided a clear step-by-step guide to achieve this:

* **Step 1: Clean and Format Your Data**
    * Language models need context to understand how to reply.
    * Filter out rows where the content is empty but has an attachment link, unless the goal is to learn link spamming.
    * When finding a message by "lustsoul", grab the previous 3 to 5 messages to use as context.
    * Format this data into a JSONL file.
* **Step 2: Set Up Google Colab**
    * Create a new notebook and select a T4 GPU.
    * Install the required libraries: `transformers`, `datasets`, `peft`, `trl`, `bitsandbytes`, and `accelerate`.
* **Step 3: Load the Data and Model**
    * Use a quantized model (like Llama-3-8B or Mistral-7B) to fit within free GPU limits.
    * Configure 4-bit quantization to save memory.
* **Step 4: Configure LoRA and Train**
    * Set up LoRA (Low-Rank Adaptation) to train the model quickly by updating only a small portion of its weights.
    * Initialize the `SFTTrainer` and start training.
* **Step 5: Test Your Fine-Tuned Model**
    * Test the model in Colab to verify it picked up catchphrases, text faces like ":3", and general timing.
    * Ensure Discord user IDs and media links are filtered out during cleaning to avoid hallucinated links.

### 3.2. Interaction 2: Addressing Off-Topic Behavior

**User Prompt:**
The user noted that in one of the provided examples, their response was completely unrelated to the ongoing conversation.

**Assistant Response:**
The assistant confirmed this observation and explained how language models learn:
* In the first example, the user directly answered a joke setup.
* In the second example, the user changed the topic entirely to ask for a voice chat.
* The AI does not inherently understand "staying on topic" and only learns sequence prediction.
* **Option 1:** Leave the interruptions in for authenticity, resulting in an AI that occasionally interrupts conversations for voice chats.
* **Option 2:** Filter out "meta" messages (like "vc?", "brb") to force the AI to strictly reply to the subject at hand.