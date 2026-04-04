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

# IMPROVED: Captures the ID from the ping to allow for mapping
USER_PING_PATTERN = re.compile(r'<@!?&?(\d+)>')
GENERAL_PING_PATTERN = re.compile(r'@(everyone|here|[a-zA-Z0-9_.-]+)')

TARGET_USER = os.getenv("TARGET_USER", "your_target_username")
KNOWN_BOTS = set(config["preprocessing"]["known_bots"])
PLACEHOLDERS = set(config["preprocessing"]["placeholders"])
MIN_CONTEXT = config["preprocessing"]["min_context_window"]
MAX_CONTEXT = config["preprocessing"]["max_context_window"]

SHORT_WC = config["preprocessing"].get("short_response_word_count", 3)
DOWNSAMPLE_RATE = config["preprocessing"].get("short_response_downsample_rate", 0.60)
MAX_MSG_WORDS = 100 

# Global map to store ID -> Username
USER_ID_MAP = {}

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
    """
    Phase 0: Scans all CSVs to build a dictionary of UserIDs to Names.
    This ensures pings are resolved even if a user appears in a different channel.
    """
    print("Building Username Map...")
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".csv"):
                try:
                    with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            author_name = row.get("Author", "").strip()
                            # Some exports include 'AuthorID' or 'User ID'
                            author_id = row.get("AuthorID") or row.get("User ID")
                            
                            if author_name and author_id:
                                # Clean potential discriminator (Name#1234 -> Name)
                                clean_name = author_name.split('#')[0]
                                USER_ID_MAP[str(author_id)] = clean_name
                except Exception:
                    continue
    print(f"Mapped {len(USER_ID_MAP)} unique users.")

def resolve_mentions(content):
    """Replaces <@12345> with @Name using the discovered map."""
    def replace_match(match):
        uid = match.group(1)
        return f"@{USER_ID_MAP.get(uid, 'User')}"
    
    return USER_PING_PATTERN.sub(replace_match, content)

def extract_pairs_from_csv(filepath, min_context_window=MIN_CONTEXT, max_context_window=MAX_CONTEXT):
    dataset = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            grouped_messages = []
            
            for row in reader:
                author = row.get("Author", "").strip()
                content = row.get("Content", "").replace('\n', ' ').replace('\r', '')
                attachments = row.get("Attachments", "").strip()
                date_str = row.get("Date", "").strip()
            
                if not author: continue
                
                author_lower = author.lower()
                if BOT_PATTERN.search(author) or "bot" in author_lower or author_lower in KNOWN_BOTS:
                    continue
                    
                content = UNICODE_SPAM_PATTERN.sub('', content).strip()
                
                # IMPROVED: Resolve mentions using the map instead of generic [User]
                content = resolve_mentions(content)
                content = GENERAL_PING_PATTERN.sub(r'\1', content)
                content = content.replace('<', '').replace('>', '')
                
                if not content and attachments:
                    content = "[Attachment]"
                elif not content:
                    content = "[Empty/Reaction]"
                    
                content = MARKDOWN_LINK_PATTERN.sub(r'\1 [Link]', content)
                cleaned_content = URL_PATTERN.sub("[Link]", content).strip()
                
                if SYSTEM_MSG_PATTERN.search(cleaned_content) or COMMAND_PATTERN.search(cleaned_content):
                    continue
                    
                msg_time = parse_date(date_str)
                
                if grouped_messages:
                    last_msg = grouped_messages[-1]
                    is_within_time = False
                    if msg_time and last_msg['time']:
                        time_delta_sec = (msg_time - last_msg['time']).total_seconds()
                        is_within_time = (time_delta_sec < 3600)
                    
                    is_same_author = (last_msg['author'].lower() == author.lower())
                    
                    if is_same_author and is_within_time:
                        if last_msg['content'] == "[Empty/Reaction]":
                            last_msg['content'] = cleaned_content
                        elif cleaned_content != "[Empty/Reaction]":
                            last_msg['content'] += f" {cleaned_content}"
                        if msg_time:
                            last_msg['time'] = msg_time
                        continue
                        
                grouped_messages.append({
                    "author": author.split('#')[0], # Clean discriminator for consistency
                    "content": cleaned_content,
                    "time": msg_time
                })
               
            context_queue = []
            last_time = None
            
            for msg in grouped_messages:
                author = msg['author']
                cleaned_content = msg['content']
                msg_time = msg['time']
                
                if last_time and msg_time:
                    if (msg_time - last_time).total_seconds() > 3600:
                        context_queue.clear()
                        
                if msg_time: last_time = msg_time
                
                is_target = author.lower() == TARGET_USER.lower()
                word_count = len(cleaned_content.split())
                
                if is_target and word_count > MAX_MSG_WORDS:
                    continue

                skip_due_to_downsampling = False
                if is_target and word_count < SHORT_WC:
                    if random.random() < DOWNSAMPLE_RATE:
                        skip_due_to_downsampling = True

                if is_target and not skip_due_to_downsampling:
                    if len(context_queue) >= min_context_window:
                        target_response = cleaned_content
                        for p in PLACEHOLDERS:
                            target_response = target_response.replace(p, "")
                        target_response = " ".join(target_response.split())
                            
                        if target_response: 
                            context_words = []
                            for c in context_queue:
                                context_words.extend(c['content'].split())
                                
                            total_words = len(context_words)
                            placeholder_count = sum(1 for w in context_words if any(p in w for p in PLACEHOLDERS))
                            placeholder_ratio = placeholder_count / total_words if total_words > 0 else 0
                            
                            if placeholder_ratio <= 0.5:
                                lang_hint = ""
                                if len(target_response.split()) >= 6:
                                    try:
                                        lang = detect(target_response)
                                        lang_map = {'en': 'English', 'cs': 'Czech', 'de': 'German'}
                                        if lang in lang_map:
                                            lang_hint = f" Respond in {lang_map[lang]}."
                                    except Exception: pass
                                        
                                system_prompt = f"You are {TARGET_USER} in a Discord chat.{lang_hint}"
                                messages = [{"role": "system", "content": system_prompt}]
                                
                                for ctx_msg in context_queue:
                                    role = "assistant" if ctx_msg["author"].lower() == TARGET_USER.lower() else "user"
                                    ctx_words = ctx_msg['content'].split()
                                    
                                    # History truncation (only for context, not target)
                                    if len(ctx_words) > MAX_MSG_WORDS:
                                        content_str = " ".join(ctx_words[:MAX_MSG_WORDS]) + "..."
                                    else:
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
        print("Error: SOURCE_DIR not found.")
        return
        
    # Step 1: Discover usernames to populate the map
    build_global_user_map(source_dir)

    output_dir = config["directories"]["output"]
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, config["files"]["dataset"])

    dataset = []
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".csv"):
                dataset.extend(extract_pairs_from_csv(os.path.join(root, file)))

    with open(output_file, 'w', encoding='utf-8') as f:
        for entry in dataset:
            f.write(json.dumps(entry) + "\n")

    print(f"Done. {len(dataset)} pairs saved to {output_file}.")

if __name__ == "__main__":
    process_discord_logs()