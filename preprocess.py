import os
import csv
import re
import json
from dotenv import load_dotenv

def process_discord_logs():
    load_dotenv()
    source_dir = os.getenv("SOURCE_DIR")

    if not source_dir:
        print("Error: SOURCE_DIR not found in .env file.")
        return

    output_dir = "processed"
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "dataset.jsonl")

    url_pattern = re.compile(r'http[s]?://\S+')
    
    dataset = []
    max_context_window = 5 
    min_context_window = 3

    for root, dirs, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".csv"):
                filepath = os.path.join(root, file)
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        context_queue = []
                        
                        for row in reader:
                            author = row.get("Author", "").strip()
                            content = row.get("Content", "").strip()
                            attachments = row.get("Attachments", "").strip()
                            
                            if not author:
                                continue
                            
                            if not content and attachments:
                                content = "[Attachment]"
                            elif not content:
                                content = "[Empty/Reaction]"
                                
                            cleaned_content = url_pattern.sub("[Link]", content).strip()
                                
                            if author == "lustsoul":
                                if len(context_queue) >= min_context_window:
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
                    print(f"Could not process {file}: {e}")

    with open(output_file, 'w', encoding='utf-8') as f:
        for entry in dataset:
            f.write(json.dumps(entry) + "\n")

    print(f"Processing complete. {len(dataset)} context pairs saved to {output_file}.")

if __name__ == "__main__":
    process_discord_logs()