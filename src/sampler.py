import os
import csv
import re
import json
import random
from dotenv import load_dotenv

def generate_samples():
    load_dotenv()
    source_dir = os.getenv("SOURCE_DIR")

    if not source_dir:
        print("Error: SOURCE_DIR not found in .env file.")
        return

    output_dir = "processed"
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "samples.jsonl")

    # Regex patterns for cleaning and filtering
    url_pattern = re.compile(r'http[s]?://\S+')
    unicode_spam_pattern = re.compile(r'[\u1cbc\u200b\u200c\u200d\u200e\u200f\u2028\u2029\u2800]+')
    bot_pattern = re.compile(r'#\d{4}$')
    system_msg_pattern = re.compile(r'^(Started a call that lasted|Added .* to the group|Left the group|Changed the channel|Pinned a message)', re.IGNORECASE)
    
    placeholders = {"[Attachment]", "[Link]", "[Empty/Reaction]"}
    
    csv_files = []
    for root, dirs, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".csv"):
                csv_files.append(os.path.join(root, file))
    
    if not csv_files:
        print("No CSV files found.")
        return

    target_total_samples = 30
    samples_per_file = max(1, target_total_samples // len(csv_files))

    dataset = []
    max_context_window = 5 
    min_context_window = 3

    for filepath in csv_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                context_queue = []
                file_samples = []
                
                for row in reader:
                    author = row.get("Author", "").strip()
                    # Replace newlines with spaces to prevent multiline message confusion
                    content = row.get("Content", "").replace('\n', ' ').replace('\r', '')
                    attachments = row.get("Attachments", "").strip()
                    
                    if not author:
                        continue
                        
                    # Filter out known bots and Discord discriminators
                    if bot_pattern.search(author) or "bot" in author.lower() or "promptinspector" in author.lower():
                        continue
                        
                    # Strip invisible unicode spam before checking if empty
                    content = unicode_spam_pattern.sub('', content).strip()
                    
                    if not content and attachments:
                        content = "[Attachment]"
                    elif not content:
                        content = "[Empty/Reaction]"
                        
                    cleaned_content = url_pattern.sub("[Link]", content).strip()
                    
                    # Filter out automated system action messages
                    if system_msg_pattern.search(cleaned_content):
                        continue
                        
                    if author == "lustsoul":
                        if len(context_queue) >= min_context_window:
                            
                            # Prevent target responses that are solely placeholders
                            if cleaned_content not in placeholders:
                                
                                # Check if the entire context queue is just placeholders
                                context_values = [msg.split(": ", 1)[1] for msg in context_queue if ": " in msg]
                                all_placeholders = all(val in placeholders for val in context_values)
                                
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
                                    file_samples.append(data_point)
                                
                        context_queue.append(f"{author}: {cleaned_content}")
                    else:
                        context_queue.append(f"{author}: {cleaned_content}")
                        
                    if len(context_queue) > max_context_window:
                        context_queue.pop(0)

                if len(file_samples) > samples_per_file:
                    dataset.extend(random.sample(file_samples, samples_per_file))
                else:
                    dataset.extend(file_samples)

        except Exception as e:
            print(f"Could not process {filepath}: {e}")

    with open(output_file, 'w', encoding='utf-8') as f:
        for entry in dataset:
            f.write(json.dumps(entry) + "\n")

    print(f"Sampling complete. {len(dataset)} context pairs saved to {output_file}.")

if __name__ == "__main__":
    generate_samples()