import os
import csv
import re
import json
from dotenv import load_dotenv

# Regex patterns globally defined for efficiency
URL_PATTERN = re.compile(r'http[s]?://\S+')
MARKDOWN_LINK_PATTERN = re.compile(r'\[([^\]]*)\]\(http[s]?://[^\)]+\)')
UNICODE_SPAM_PATTERN = re.compile(r'[\u1cbc\u200b\u200c\u200d\u200e\u200f\u2028\u2029\u2800]+')
BOT_PATTERN = re.compile(r'#\d{4}$')
SYSTEM_MSG_PATTERN = re.compile(r'^(Started a call that lasted|Added .* to the group|Left the group|Changed the channel|Pinned a message)', re.IGNORECASE)
COMMAND_PATTERN = re.compile(r'^([!/?\.\-]|p!|m!|p\|)\w+', re.IGNORECASE)

KNOWN_BOTS = {"clyde", "freestuff", "system"}
PLACEHOLDERS = {"[Attachment]", "[Link]", "[Empty/Reaction]"}

def extract_pairs_from_csv(filepath, min_context_window=3, max_context_window=5):
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
                
                if not content and attachments:
                    content = "[Attachment]"
                elif not content:
                    content = "[Empty/Reaction]"
                    
                content = MARKDOWN_LINK_PATTERN.sub(r'\1 [Link]', content)
                cleaned_content = URL_PATTERN.sub("[Link]", content).strip()
                
                if SYSTEM_MSG_PATTERN.search(cleaned_content) or COMMAND_PATTERN.search(cleaned_content):
                    continue
                    
                if author == "lustsoul":
                    if len(context_queue) >= min_context_window:
                        if cleaned_content not in PLACEHOLDERS:
                            context_values = [msg.split(": ", 1)[1] for msg in context_queue if ": " in msg]
                            all_placeholders = all(val in PLACEHOLDERS for val in context_values)
                            
                            if not all_placeholders:
                                system_prompt = "You are lustsoul in a Discord chat."
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
    load_dotenv()
    source_dir = os.getenv("SOURCE_DIR")

    if not source_dir:
        print("Error: SOURCE_DIR not found in .env file.")
        return

    output_dir = "processed"
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "dataset.jsonl")

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