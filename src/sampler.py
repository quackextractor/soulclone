import os
import random
import yaml
import json
import re
import pyzipper
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

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
        print(f"Error: {dataset_file} not found. Please run 'preprocess.py' first.")
        return

    # Read preprocessed dataset
    dataset = []
    with open(dataset_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                dataset.append(json.loads(line))

    # Multi-Dimensional Bucketing: Group by Language, then by Length
    lang_buckets = {}
    for item in dataset:
        lang = item.get("language", "Unknown")
        if lang not in lang_buckets:
            lang_buckets[lang] = {"short": [], "medium": [], "long": []}
        
        messages = item.get("messages", [])
        word_count = 0
        
        # Calculate length of the target assistant response
        for msg in reversed(messages):
            if msg["role"] == "assistant":
                content_clean = re.sub(r'^\[.*?\]:\s*', '', msg["content"])
                word_count = len(content_clean.split())
                break
                
        bucket = "long"
        if word_count <= short_max:
            bucket = "short"
        elif word_count <= medium_max:
            bucket = "medium"
            
        lang_buckets[lang][bucket].append(item)

    # Calculate fair quotas per language
    lang_counts = {lang: sum(len(b) for b in buckets.values()) for lang, buckets in lang_buckets.items()}
    remaining_target = target_total
    remaining_langs = list(lang_counts.keys())
    lang_quotas = {lang: 0 for lang in remaining_langs}
    
    # Distribute the target quota fairly to balance minority languages
    while remaining_langs and remaining_target > 0:
        avg_quota = remaining_target // len(remaining_langs)
        small_langs = [l for l in remaining_langs if lang_counts[l] < avg_quota]
        
        if small_langs:
            # If a language has fewer messages than the average quota, take all of them
            for l in small_langs:
                lang_quotas[l] = lang_counts[l]
                remaining_target -= lang_counts[l]
                remaining_langs.remove(l)
        else:
            # Distribute evenly among remaining large languages
            for l in remaining_langs:
                lang_quotas[l] += avg_quota
                remaining_target -= avg_quota
            # Handle remainder division
            for i in range(remaining_target):
                lang_quotas[remaining_langs[i]] += 1
            remaining_target = 0
            break

    sampled_data = []
    sample_stats = {
        "total_samples": 0,
        "language_distribution": {},
        "target_length_distribution": {
            "short_pct": short_pct,
            "medium_pct": medium_pct,
            "long_pct": long_pct
        },
        "actual_user_distribution": {}
    }

    # Sample within each language block to enforce 40/40/20 length rules
    for lang, quota in lang_quotas.items():
        if quota == 0: continue
        
        short_target = int(quota * short_pct)
        medium_target = int(quota * medium_pct)
        long_target = quota - short_target - medium_target
        
        buckets = lang_buckets[lang]
        random.shuffle(buckets["short"])
        random.shuffle(buckets["medium"])
        random.shuffle(buckets["long"])
        
        lang_sampled = []
        
        # Fill short
        taken_short = min(short_target, len(buckets["short"]))
        lang_sampled.extend(buckets["short"][:taken_short])
        short_deficit = short_target - taken_short
        
        # Fill medium (absorb short deficit if needed)
        medium_target += short_deficit
        taken_medium = min(medium_target, len(buckets["medium"]))
        lang_sampled.extend(buckets["medium"][:taken_medium])
        medium_deficit = medium_target - taken_medium
        
        # Fill long (absorb medium deficit if needed)
        long_target += medium_deficit
        taken_long = min(long_target, len(buckets["long"]))
        lang_sampled.extend(buckets["long"][:taken_long])
        long_deficit = long_target - taken_long
        
        # Backfill from any remaining pool if there's still a deficit
        if long_deficit > 0:
            rem_short = buckets["short"][taken_short:]
            rem_medium = buckets["medium"][taken_medium:]
            pool = rem_short + rem_medium
            random.shuffle(pool)
            lang_sampled.extend(pool[:long_deficit])
            
        sampled_data.extend(lang_sampled)
        sample_stats["language_distribution"][lang] = len(lang_sampled)

    # Shuffle the final compiled dataset so languages aren't clustered
    random.shuffle(sampled_data)

    # Write out data
    with open(samples_file, 'w', encoding='utf-8') as f:
        for item in sampled_data:
            # Drop the internal 'language' tag before saving so Hugging Face can read it normally
            clean_item = {"messages": item["messages"]}
            f.write(json.dumps(clean_item, ensure_ascii=False) + "\n")
            
            sample_stats["total_samples"] += 1
            
            # Update user stats for sample_summary.json
            try:
                user_msg = item["messages"][1]["content"]
                username_match = re.match(r'^\[(.*?)\]:', user_msg)
                if username_match:
                    username = username_match.group(1)
                    
                    # Determine bucket for final summary
                    word_count = 0
                    for msg in reversed(item["messages"]):
                        if msg["role"] == "assistant":
                            content_clean = re.sub(r'^\[.*?\]:\s*', '', msg["content"])
                            word_count = len(content_clean.split())
                            break
                            
                    bucket = "long"
                    if word_count <= short_max: bucket = "short"
                    elif word_count <= medium_max: bucket = "medium"

                    if username not in sample_stats["actual_user_distribution"]:
                        sample_stats["actual_user_distribution"][username] = {
                            "total": 0, "short": 0, "medium": 0, "long": 0
                        }
                        
                    sample_stats["actual_user_distribution"][username]["total"] += 1
                    sample_stats["actual_user_distribution"][username][bucket] += 1
            except Exception:
                pass

    sample_summary_file = os.path.join(output_dir, "sample_summary.json")
    with open(sample_summary_file, 'w', encoding='utf-8') as f:
        json.dump(sample_stats, f, indent=4)
        
    print(f"Sample summary written to {sample_summary_file}.")

    # --- Zipping Logic ---
    zip_password = os.getenv("ZIP_PASSWORD")
    if zip_password:
        zip_path = os.path.join(output_dir, "processed_samples.zip")
        print(f"Securing sampled dataset into encrypted zip: {zip_path}...")
        try:
            with pyzipper.AESZipFile(zip_path, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
                zf.pwd = zip_password.encode('utf-8')
                zf.write(samples_file, arcname=config["files"]["samples"])
                zf.write(sample_summary_file, arcname="sample_summary.json")
            print(f"Encrypted zip created at: {zip_path}")
        except Exception as e:
            print(f"Failed to create encrypted zip: {e}")

if __name__ == "__main__":
    generate_samples()