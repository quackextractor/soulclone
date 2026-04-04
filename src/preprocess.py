import os
import csv
import re
import json
import yaml
import random
from datetime import datetime
from dotenv import load_dotenv
from langdetect import detect, DetectorFactory

# Ensure consistent results from langdetect
DetectorFactory.seed = 0

# Load environment variables early for global access
load_dotenv()

# Load configuration
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Regex patterns globally defined for efficiency
URL_PATTERN = re.compile(r'http[s]?://\S+')
MARKDOWN_LINK_PATTERN = re.compile(r'\[([^\]]*)\]\(http[s]?://[^\)]+\)')
UNICODE_SPAM_PATTERN = re.compile(r'[\u1cbc\u200b\u200c\u200d\u200e\u200f\u2028\u2029\u2800]+')
BOT_PATTERN = re.compile(r'#\d{4}$')
SYSTEM_MSG_PATTERN = re.compile(r'^(Started a call that lasted|Added .* to the group|Left the group|Changed the channel|Pinned a message)', re.IGNORECASE)
COMMAND_PATTERN = re.compile(r'^([!/?\.\-]|p!|m!|p\|)\w+', re.IGNORECASE)

# FIXED: Removed the capture group that caused unmatched group errors
USER_PING_PATTERN = re.compile(r'<@&?\d+>')
GENERAL_PING_PATTERN = re.compile(r'@(everyone|here|[a-zA-Z0-9_.-]+)')

TARGET_USER = os.getenv("TARGET_USER", "your_target_username")
KNOWN_BOTS = set(config["preprocessing"]["known_bots"])
PLACEHOLDERS = set(config["preprocessing"]["placeholders"])
MIN_CONTEXT = config["preprocessing"]["min_context_window"]
MAX_CONTEXT = config["preprocessing"]["max_context_window"]

# Configurable downsampling and truncation parameters
SHORT_WC = config["preprocessing"].get("short_response_word_count", 3)
DOWNSAMPLE_RATE = config["preprocessing"].get("short_response_downsample_rate", 0.60)
MAX_MSG_WORDS = 100 # Prevents copypastas from truncating the target response

def parse_date(date_str):
    """Helper to parse common Discord export timestamp formats."""
    if not date_str:
        return None
    try:
        date_str = date_str.replace('Z', '+00:00')
        return datetime.fromisoformat(date_str)
    except ValueError:
        try:
            clean_str = date_str.split('.')[0].replace('T', ' ')
            return datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

def extract_pairs_from_csv(filepath, min_context_window=MIN_CONTEXT, max_context_window=MAX_CONTEXT):
    """Reads a single CSV and returns a list of cleaned JSONL context pairs."""
    dataset = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # --- Phase 1: Grouping & Cleaning ---
            grouped_messages = []
            
            for row in reader:
                author = row.get("Author", "").strip()
                content = row.get("Content", "").replace('\n', ' ').replace('\r', '')
                attachments = row.get("Attachments", "").strip()
                date_str = row.get("Date", "").strip()
            
                if not author:
                    continue
                
                author_lower = author.lower()
                if BOT_PATTERN.search(author) or "bot" in author_lower or "promptinspector" in author_lower or author_lower in KNOWN_BOTS:
                    continue
                    
                content = UNICODE_SPAM_PATTERN.sub('', content).strip()
                
                # FIXED: Safer ping replacement to avoid re.error: unmatched group
                content = USER_PING_PATTERN.sub('', content)
                content = GENERAL_PING_PATTERN.sub(r'\1', content)
                content = content.replace('<', '').replace('>', '')
                
                if not content and attachments:
                    content = "[Attachment]"
                elif not content:
                    content = "[Empty/Reaction]"
                    
                content = MARKDOWN_LINK_PATTERN.sub(r'\1 [Link]', content)
                cleaned_content = URL_PATTERN.sub("[Link]", content).strip()
                
                # Truncate extremely long messages to protect context window
                words = cleaned_content.split()
                if len(words) > MAX_MSG_WORDS:
                    cleaned_content = " ".join(words[:MAX_MSG_WORDS]) + "..."
                
                if SYSTEM_MSG_PATTERN.search(cleaned_content) or COMMAND_PATTERN.search(cleaned_content):
                    continue
                    
                msg_time = parse_date(date_str)
                
                if grouped_messages:
                    last_msg = grouped_messages[-1]
                    time_delta_sec = (msg_time - last_msg['time']).total_seconds() if msg_time and last_msg['time'] else 0
                    
                    is_same_author = (last_msg['author'].lower() == author.lower())
                    is_within_time = (time_delta_sec < 3600)
                    
                    if is_same_author and is_within_time:
                        if last_msg['content'] == "[Empty/Reaction]":
                            last_msg['content'] = cleaned_content
                        elif cleaned_content != "[Empty/Reaction]":
                            last_msg['content'] += f" {cleaned_content}"
                        
                        if msg_time:
                            last_msg['time'] = msg_time
                        continue
                        
                grouped_messages.append({
                    "author": author,
                    "content": cleaned_content,
                    "time": msg_time
                })
               
            # --- Phase 2: Context Queueing & Generation ---
            context_queue = []
            last_time = None
            
            for msg in grouped_messages:
                author = msg['author']
                cleaned_content = msg['content']
                msg_time = msg['time']
                
                if last_time and msg_time:
                    if (msg_time - last_time).total_seconds() > 3600:
                        context_queue.clear()
                        
                if msg_time:
                    last_time = msg_time
                
                is_target = author.lower() == TARGET_USER.lower()
                word_count = len(cleaned_content.split())
                
                skip_due_to_downsampling = False
                if is_target and word_count < SHORT_WC:
                    if random.random() < DOWNSAMPLE_RATE:
                        skip_due_to_downsampling = True

                if is_target and not skip_due_to_downsampling:
                    if len(context_queue) >= min_context_window:
                        
                        target_response = cleaned_content
                        for p in PLACEHOLDERS:
                            target_response = target_response.replace(p, "").strip()
                            
                        if target_response: 
                            # Calculate placeholder ratio for the context
                            context_words = []
                            for c in context_queue:
                                context_words.extend(c['content'].split())
                                
                            total_words = len(context_words)
                            placeholder_count = sum(1 for w in context_words if any(p in w for p in PLACEHOLDERS))
                            placeholder_ratio = placeholder_count / total_words if total_words > 0 else 0
                            all_placeholders = (total_words == placeholder_count) and (total_words > 0)
                            
                            # Proceed only if the context isn't overrun with placeholders
                            if placeholder_ratio <= 0.5 and not all_placeholders:
                                lang_hint = ""
                                # Only detect language if string is long enough to be accurate
                                if len(target_response.split()) >= 3:
                                    try:
                                        lang = detect(target_response)
                                        lang_map = {'en': 'English', 'cs': 'Czech', 'de': 'German'}
                                        if lang in lang_map:
                                            lang_hint = f" Respond in {lang_map[lang]}."
                                    except Exception:
                                        pass
                                        
                                system_prompt = f"You are {TARGET_USER} in a Discord chat.{lang_hint}"
                                messages = [{"role": "system", "content": system_prompt}]
                                
                                for ctx_msg in context_queue:
                                    role = "assistant" if ctx_msg["author"].lower() == TARGET_USER.lower() else "user"
                                    content_str = ctx_msg['content']
                                    
                                    if role == "user":
                                        content_str = f"{ctx_msg['author']}: {content_str}"
                                        
                                    if messages[-1]["role"] == role:
                                        messages[-1]["content"] += f"\n{content_str}"
                                    else:
                                        messages.append({"role": role, "content": content_str})
                                            
                                messages.append({"role": "assistant", "content": target_response})
                                dataset.append({"messages": messages})
                                    
                context_queue.append({"author": author, "content": cleaned_content})
                if len(context_queue) > max_context_window:
                    context_queue.pop(0)

    except Exception as e:
        print(f"Could not process {filepath}: {e}")
        
    return dataset

def process_discord_logs():
    source_dir = os.getenv("SOURCE_DIR")
    if not source_dir:
        print("Error: SOURCE_DIR not found in .env file.")
        return
        
    if TARGET_USER == "your_target_username":
        print("Warning: TARGET_USER is not set in .env file.")

    output_dir = config["directories"]["output"]
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, config["files"]["dataset"])

    dataset = []
    for root, dirs, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".csv"):
                filepath = os.path.join(root, file)
                dataset.extend(extract_pairs_from_csv(filepath))

    with open(output_file, 'w', encoding='utf-8') as f:
        for entry in dataset:
            f.write(json.dumps(entry) + "\n")

    print(f"Processing complete. {len(dataset)} context pairs saved to {output_file}.")

if __name__ == "__main__":
    process_discord_logs()