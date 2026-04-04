import os
import csv
import re
import json
import yaml
from dotenv import load_dotenv

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
PING_PATTERN = re.compile(r'<@&?\d+>|@(everyone|here|[a-zA-Z0-9_.-]+)')

TARGET_USER = os.getenv("TARGET_USER", "your_target_username")
KNOWN_BOTS = set(config["preprocessing"]["known_bots"])
PLACEHOLDERS = set(config["preprocessing"]["placeholders"])
MIN_CONTEXT = config["preprocessing"]["min_context_window"]
MAX_CONTEXT = config["preprocessing"]["max_context_window"]

def extract_pairs_from_csv(filepath, min_context_window=MIN_CONTEXT, max_context_window=MAX_CONTEXT):
    """Reads a single CSV and returns a list of cleaned JSONL context pairs."""
    dataset = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            context_queue = []
            
            for row in reader:
                author = row.get("Author", "").strip()
                content = row.get("Content", "").replace('\n', ' ').replace('\r', '')
                attachments = row.get("Attachments", "").strip()
                
                if not author:
                    continue
                
                author_lower = author.lower()
                if BOT_PATTERN.search(author) or "bot" in author_lower or "promptinspector" in author_lower or author_lower in KNOWN_BOTS:
                    continue
                    
                content = UNICODE_SPAM_PATTERN.sub('', content).strip()
                
                # Sanitize pings by removing the @ symbol or brackets, leaving just the name
                content = PING_PATTERN.sub(r'\1', content)
                content = content.replace('<', '').replace('>', '')
                
                if not content and attachments:
                    content = "[Attachment]"
                elif not content:
                    content = "[Empty/Reaction]"
                    
                content = MARKDOWN_LINK_PATTERN.sub(r'\1 [Link]', content)
                cleaned_content = URL_PATTERN.sub("[Link]", content).strip()
                
                if SYSTEM_MSG_PATTERN.search(cleaned_content) or COMMAND_PATTERN.search(cleaned_content):
                    continue
                    
                # Dynamic check for the target user (case-insensitive)
                if author.lower() == TARGET_USER.lower():
                    if len(context_queue) >= min_context_window:
                        if cleaned_content not in PLACEHOLDERS:
                            context_values = [msg.split(": ", 1)[1] for msg in context_queue if ": " in msg]
                            all_placeholders = all(val in PLACEHOLDERS for val in context_values)
                            
                            if not all_placeholders:
                                # Inject target user into the system prompt
                                system_prompt = f"You are {TARGET_USER} in a Discord chat."
                                user_context = "\n".join(context_queue)
                                
                                data_point = {
                                    "messages": [
                                        {"role": "system", "content": system_prompt},
                                        {"role": "user", "content": user_context},
                                        {"role": "assistant", "content": cleaned_content}
                                    ]
                                }
                                dataset.append(data_point)
                    
                    context_queue.append(f"{author}: {cleaned_content}")
                else:
                    context_queue.append(f"{author}: {cleaned_content}")
                    
                if len(context_queue) > max_context_window:
                    context_queue.pop(0)
    except Exception as e:
        print(f"Could not process {filepath}: {e}")
        
    return dataset

def process_discord_logs():
    # load_dotenv() removed from here since it's now at the top
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