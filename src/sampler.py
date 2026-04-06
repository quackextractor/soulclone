import os
import random
import yaml
import json
import re

def generate_samples():
    # Load configuration
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    output_dir = config["directories"]["output"]
    dataset_file = os.path.join(output_dir, config["files"]["dataset"])
    samples_file = os.path.join(output_dir, config["files"]["samples"])
    target_total = config["sampling"]["target_total_samples"]
    
    # Load Response Distribution Settings
    dist_config = config["sampling"].get("response_distribution", {})
    short_max = dist_config.get("short_max_words", 5)
    medium_max = dist_config.get("medium_max_words", 20)
    
    short_pct = dist_config.get("short_target_pct", 0.40)
    medium_pct = dist_config.get("medium_target_pct", 0.40)
    long_pct = dist_config.get("long_target_pct", 0.20)

    if not os.path.exists(dataset_file):
        print(f"Error: {dataset_file} not found. Please run 'preprocess' first to generate the dataset.")
        return

    # Read preprocessed lines directly
    with open(dataset_file, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()

    if not all_lines:
        print("Error: The dataset file is empty.")
        return

    target_total = min(target_total, len(all_lines))

    user_data = {}
    # Structure: { username: {'short': [], 'medium': [], 'long': [], 'all': []} }
    
    username_pattern = re.compile(r'^\[(.*?)\]:')

    # Phase 1: Categorize all data by Interlocutor and Response Length
    for line in all_lines:
        try:
            data = json.loads(line)
            messages = data.get("messages", [])
            
            # Find the last user message to extract their username
            username = "unknown"
            for msg in reversed(messages):
                if msg["role"] == "user":
                    match = username_pattern.search(msg["content"])
                    if match:
                        username = match.group(1)
                    break
            
            # Find assistant response to calculate word count
            word_count = 0
            for msg in reversed(messages):
                if msg["role"] == "assistant":
                    word_count = len(msg["content"].split())
                    break
                    
            bucket = "long"
            if word_count <= short_max:
                bucket = "short"
            elif word_count <= medium_max:
                bucket = "medium"

            if username not in user_data:
                user_data[username] = {'short': [], 'medium': [], 'long': [], 'all': []}
            
            user_data[username][bucket].append(line)
            user_data[username]['all'].append(line)
        except Exception:
            continue

    sampled_lines = []
    total_available = sum(len(u['all']) for u in user_data.values())
    picked_lines = set()

    # Phase 2: Stratified proportional sampling
    for username, buckets in user_data.items():
        user_total = len(buckets['all'])
        user_ratio = user_total / total_available
        user_target = int(round(user_ratio * target_total))
        
        if user_target == 0:
            continue

        target_short = int(round(user_target * short_pct))
        target_medium = int(round(user_target * medium_pct))
        target_long = user_target - target_short - target_medium # Remainder to avoid rounding drops

        def sample_from_bucket(b_name, count):
            available = [l for l in buckets[b_name] if l not in picked_lines]
            picked = random.sample(available, min(count, len(available)))
            picked_lines.update(picked)
            sampled_lines.extend(picked)
            return len(picked)

        short_picked = sample_from_bucket('short', target_short)
        medium_picked = sample_from_bucket('medium', target_medium)
        long_picked = sample_from_bucket('long', target_long)

        # Handle deficits: If a user didn't have enough short messages, fill the gap with their medium/long messages
        user_deficit = user_target - (short_picked + medium_picked + long_picked)
        if user_deficit > 0:
            available_any = [l for l in buckets['all'] if l not in picked_lines]
            fallback_picked = random.sample(available_any, min(user_deficit, len(available_any)))
            picked_lines.update(fallback_picked)
            sampled_lines.extend(fallback_picked)

    # Phase 3: Global deficit fill (To account for rounding errors or severe user deficits)
    global_deficit = target_total - len(sampled_lines)
    if global_deficit > 0:
        remaining_global = [l for l in all_lines if l not in picked_lines]
        fallback_global = random.sample(remaining_global, min(global_deficit, len(remaining_global)))
        sampled_lines.extend(fallback_global)

    # Shuffle the final dataset to mix users and sizes for training
    random.shuffle(sampled_lines)

    # Save to samples file
    with open(samples_file, 'w', encoding='utf-8') as f:
        for line in sampled_lines:
            f.write(line)

    print(f"Sampling complete. {len(sampled_lines)} context pairs proportionally balanced and saved to {samples_file}.")

if __name__ == "__main__":
    generate_samples()