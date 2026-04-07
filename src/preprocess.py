import os
import csv
import re
import json
import yaml
import random
from datetime import datetime
from dotenv import load_dotenv
from langdetect import detect, DetectorFactory
from tqdm import tqdm

# Ensure consistent results from langdetect
DetectorFactory.seed = 0

# Load environment variables
load_dotenv()

# Load configuration
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# Regex patterns
URL_PATTERN = re.compile(r'http[s]?://\S+')
MARKDOWN_LINK_PATTERN = re.compile(r'\[([^\]]*)\]\(http[s]?://[^\)]+\)')
UNICODE_SPAM_PATTERN = re.compile(r'[\u1cbc\u200b\u200c\u200d\u200e\u200f\u2028\u2029\u2800]+')
BOT_PATTERN = re.compile(r'#\d{4}$')
SYSTEM_MSG_PATTERN = re.compile(r'^(Started a call that lasted|Added .* to the group|Left the group|Changed the channel|Pinned a message)', re.IGNORECASE)
COMMAND_PATTERN = re.compile(r'^([!/?\.\-]|p!|m!|p\|)\w+', re.IGNORECASE)

# Captures the ID from the ping to allow for mapping
USER_PING_PATTERN = re.compile(r'<@!?&?(\d+)>')
GENERAL_PING_PATTERN = re.compile(r'@(everyone|here|[a-zA-Z0-9_.-]+)')

TARGET_USER = os.getenv("TARGET_USER", "your_target_username")
KNOWN_BOTS = set(config["preprocessing"]["known_bots"])
IGNORE_USERS = set([u.lower() for u in config["preprocessing"].get("ignore_users", [])])
PLACEHOLDERS = set(config["preprocessing"]["placeholders"])
MIN_CONTEXT = max(config["preprocessing"].get("min_context_window", 4), 4)
MAX_CONTEXT = config["preprocessing"]["max_context_window"]
MAX_MSG_WORDS = config["preprocessing"].get("max_msg_words", 100)
MAX_TIME_DELTA = config["preprocessing"].get("max_time_delta_seconds", 3600)
SHORT_WC = config["preprocessing"].get("short_response_word_count", 3)
DOWNSAMPLE_RATE = config["preprocessing"].get("short_response_downsample_rate", 0.60)
DROP_ATTACHMENT_ONLY = config["preprocessing"].get("drop_attachment_only_responses", True)
MIN_WORDS_LANG_DETECT = config["preprocessing"].get("min_words_for_language_detect", 6)
LANG_MAP = config["preprocessing"].get("lang_map", {})

# Language detection mode: A (None), B (Summary only), C (Summary + Hints)
LANG_MODE = config["preprocessing"].get("language_detection_mode", "B").upper()

# Global map to store ID -> Username
USER_ID_MAP = {}

# Global stats tracking
stats = {
    "total_pairs_processed": 0,
    "short_responses_kept": 0,
    "short_responses_dropped": 0,
    "attachment_only_responses_dropped": 0,
    "languages_detected": {}
}

def parse_date(date_str):
    if not date_str: return None
    try:
        date_str = date_str.replace('Z', '+00:00')
        return datetime.fromisoformat(date_str)
    except ValueError:
        try:
            clean_str = date_str.split('.')[0].replace('T', ' ')
            return datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

def build_global_user_map(source_dir):
    """Phase 0: Scans all CSVs to build a dictionary of UserIDs to Names."""
    print("Building Username Map...")
    
    csv_files = []
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".csv"):
                csv_files.append(os.path.join(root, file))
                
    for filepath in tqdm(csv_files, desc="Mapping Users", unit="file"):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    author_name = row.get("Author", "").strip()
                    author_id = row.get("AuthorID") or row.get("User ID")
                    if author_name and author_id:
                        clean_name = author_name.split('#')[0]
                        USER_ID_MAP[str(author_id)] = clean_name
        except Exception: continue
    print(f"Mapped {len(USER_ID_MAP)} unique users.")

def resolve_mentions(content):
    """Replaces <@12345> with @Name using the map."""
    def replace_match(match):
        uid = match.group(1)
        return f"@{USER_ID_MAP.get(uid, 'User')}"
    return USER_PING_PATTERN.sub(replace_match, content)

def clean_placeholders(text):
    """Helper to strip [Link], [Attachment], etc and fix spacing."""
    for p in PLACEHOLDERS:
        text = text.replace(p, "")
    return " ".join(text.split())

def extract_pairs_from_csv(filepath):
    dataset = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            grouped_messages = []
            
            for row in reader:
                author = row.get("Author", "").strip()
                content = row.get("Content", "")
                date_str = row.get("Date", "").strip()
            
                if not author: continue
                author_lower = author.lower()
                
                if BOT_PATTERN.search(author) or "bot" in author_lower or author_lower in KNOWN_BOTS or author_lower in IGNORE_USERS:
                    continue
                    
                content = UNICODE_SPAM_PATTERN.sub('', content).strip()
                content = resolve_mentions(content)
                content = GENERAL_PING_PATTERN.sub(r'\1', content)
                
                # Strip Markdown Links and URLs entirely instead of tagging
                cleaned_content = MARKDOWN_LINK_PATTERN.sub(r'\1', content)
                cleaned_content = URL_PATTERN.sub("", cleaned_content).strip()
                
                if not cleaned_content:
                    if author.lower() == TARGET_USER.lower() and DROP_ATTACHMENT_ONLY:
                        stats["attachment_only_responses_dropped"] += 1
                    continue
                
                if SYSTEM_MSG_PATTERN.search(cleaned_content) or COMMAND_PATTERN.search(cleaned_content):
                    continue
                    
                msg_time = parse_date(date_str)
                
                if grouped_messages:
                    last_msg = grouped_messages[-1]
                    is_within_time = False
                    if msg_time and last_msg['time']:
                        time_delta_sec = (msg_time - last_msg['time']).total_seconds()
                        is_within_time = (time_delta_sec < MAX_TIME_DELTA)
                    
                    if (last_msg['author'].lower() == author.lower()) and is_within_time:
                        last_msg['content'] += f" \n{cleaned_content}" 
                        if msg_time: last_msg['time'] = msg_time
                        continue
                        
                grouped_messages.append({
                    "author": author.split('#')[0],
                    "content": cleaned_content,
                    "time": msg_time
                })
               
            context_queue = []
            last_time = None
            
            for msg in grouped_messages:
                author = msg['author']
                raw_content = msg['content']
                msg_time = msg['time']
                
                if last_time and msg_time and (msg_time - last_time).total_seconds() > MAX_TIME_DELTA:
                    context_queue.clear()
                        
                if msg_time: last_time = msg_time
                
                is_target = author.lower() == TARGET_USER.lower()
                
                # Check if this message is the target response
                if is_target:
                    target_response = clean_placeholders(raw_content)
                    word_count = len(target_response.split())
                    
                    # 1. Skip if empty after cleaning or if too long
                    if not target_response or word_count > MAX_MSG_WORDS:
                        context_queue.append({"author": author, "content": raw_content})
                        continue

                    # 2. Downsample very short "Assistant" messages
                    if word_count < SHORT_WC:
                        if random.random() < DOWNSAMPLE_RATE:
                            stats["short_responses_dropped"] += 1
                            context_queue.append({"author": author, "content": raw_content})
                            continue
                        else:
                            stats["short_responses_kept"] += 1

                    if len(context_queue) >= MIN_CONTEXT:
                        lang_hint = ""
                        lang_name = "Unknown" # Default assignment
                        
                        # Only proceed with language detection if mode is B or C
                        if LANG_MODE in ["B", "C"] and word_count >= MIN_WORDS_LANG_DETECT:
                            try:
                                lang = detect(target_response)
                                if lang in LANG_MAP:
                                    lang_name = LANG_MAP[lang]
                                    stats["languages_detected"][lang_name] = stats["languages_detected"].get(lang_name, 0) + 1
                                    if LANG_MODE == "C":
                                        lang_hint = f" Respond in {lang_name}."
                            except:
                                pass
                                
                        messages = [{"role": "system", "content": f"You are {TARGET_USER} in a Discord chat.{lang_hint}"}]
                        
                        for ctx_msg in context_queue:
                            role = "assistant" if ctx_msg["author"].lower() == TARGET_USER.lower() else "user"
                            content_str = ctx_msg['content']
                            
                            # Clean placeholders for BOTH user and assistant
                            content_str = clean_placeholders(content_str)
                            if not content_str: continue 
                            
                            ctx_words = content_str.split()
                            if len(ctx_words) > MAX_MSG_WORDS:
                                content_str = " ".join(ctx_words[:MAX_MSG_WORDS]) + "..."
                            
                            content_str = f"[{ctx_msg['author']}]: {content_str}"
                            messages.append({"role": role, "content": content_str})
                                    
                        formatted_target = f"[{TARGET_USER}]: {target_response}"
                        messages.append({"role": "assistant", "content": formatted_target})
                        
                        # Store the language tag for the multi-dimensional sampler
                        dataset.append({
                            "language": lang_name,
                            "messages": messages
                        })
                        stats["total_pairs_processed"] += 1
                
                context_queue.append({"author": author, "content": raw_content})
                if len(context_queue) > MAX_CONTEXT:
                    context_queue.pop(0)

    except Exception as e:
        print(f"Error in {filepath}: {e}")
    return dataset

def process_discord_logs():
    source_dir = os.getenv("SOURCE_DIR")
    if not source_dir: 
        print("SOURCE_DIR not defined in .env")
        return
        
    build_global_user_map(source_dir)
    output_dir = config["directories"]["output"]
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, config["files"]["dataset"])
    summary_file = os.path.join(output_dir, config["files"]["summary"])

    csv_files = []
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".csv"):
                csv_files.append(os.path.join(root, file))

    dataset = []
    for filepath in tqdm(csv_files, desc="Processing Message Logs", unit="file"):
        dataset.extend(extract_pairs_from_csv(filepath))

    print(f"Writing dataset to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        for entry in dataset:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
    with open(summary_file, 'w', encoding='utf-8') as sf:
        json.dump(stats, sf, indent=4)
        
    print(f"Done. {len(dataset)} pairs saved to full dataset.")
    print(f"Global summary written to {summary_file}.")
    print(f"--> Proceed to run sampler.py to generate your final zipped samples.")

if __name__ == "__main__":
    process_discord_logs()