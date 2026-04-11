import os
import random
import yaml
import json
import re
import pyzipper
from dotenv import load_dotenv
from tqdm import tqdm

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
    force_balanced = config["sampling"].get("force_balanced", False)
    
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

    # Count total lines rapidly in binary mode for the progress bar
    print("Preparing to load dataset...")
    with open(dataset_file, 'rb') as f:
        total_lines = sum(1 for _ in f)

    # OPTIMIZATION: Byte-Offset Reservoir Scanning (0% RAM Crash Risk)
    lang_buckets = {}
    print("Categorizing and bucketing data (Memory-Optimized)...")
    
    with open(dataset_file, 'rb') as f:
        pbar = tqdm(total=total_lines, desc="Bucketing Offsets", unit="lines")
        while True:
            offset = f.tell()
            line = f.readline()
            if not line: break
            pbar.update(1)
            
            if not line.strip(): continue
            
            item = json.loads(line.decode('utf-8'))
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
                
            lang_buckets[lang][bucket].append(offset)
        pbar.close()

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

    sampled_offsets = []
    sample_stats = {
        "total_samples": 0,
        "force_balanced": force_balanced,
        "language_distribution": {},
        "target_length_distribution": {
            "short_pct": short_pct,
            "medium_pct": medium_pct,
            "long_pct": long_pct
        },
        "actual_length_totals": {
            "short": 0,
            "medium": 0,
            "long": 0
        },
        "actual_length_distribution_pct": {
            "short_pct": 0.0,
            "medium_pct": 0.0,
            "long_pct": 0.0
        },
        "actual_user_distribution": {},
        "bottlenecks": {}
    }

    # Sample within each language block to enforce length rules
    for lang, quota in lang_quotas.items():
        if quota == 0: continue
        
        buckets = lang_buckets[lang]
        random.shuffle(buckets["short"])
        random.shuffle(buckets["medium"])
        random.shuffle(buckets["long"])
        
        lang_sampled = []

        if force_balanced:
            # Determine maximum strict capacity bounded by the most restricted bucket
            max_short = len(buckets["short"]) / short_pct if short_pct > 0 else float('inf')
            max_medium = len(buckets["medium"]) / medium_pct if medium_pct > 0 else float('inf')
            max_long = len(buckets["long"]) / long_pct if long_pct > 0 else float('inf')
            
            capacities = {
                "quota": quota,
                "short": max_short,
                "medium": max_medium,
                "long": max_long
            }
            
            bottleneck_key = min(capacities, key=capacities.get)
            strict_total = int(capacities[bottleneck_key])
            
            # Calculate and log bottleneck statistics
            if bottleneck_key != "quota" and strict_total < quota:
                bottleneck_pct_target = {"short": short_pct, "medium": medium_pct, "long": long_pct}[bottleneck_key]
                available = len(buckets[bottleneck_key])
                required_for_quota = int(quota * bottleneck_pct_target)
                deficit = required_for_quota - available
                
                if available > 0:
                    pct_increase = round((deficit / available) * 100, 2)
                else:
                    pct_increase = "infinite"
                    
                print(f"\nLanguage '{lang}' bottlenecked by '{bottleneck_key}' bucket.")
                print(f"Missing '{bottleneck_key}' samples to reach quota: {deficit} ({pct_increase}% increase needed).")
                
                sample_stats["bottlenecks"][lang] = {
                    "cause": bottleneck_key,
                    "shortfall_plain": deficit,
                    "shortfall_percent": pct_increase
                }
            
            short_target = int(strict_total * short_pct)
            medium_target = int(strict_total * medium_pct)
            long_target = strict_total - short_target - medium_target
            
            lang_sampled.extend(buckets["short"][:short_target])
            lang_sampled.extend(buckets["medium"][:medium_target])
            lang_sampled.extend(buckets["long"][:long_target])
            
        else:
            # Legacy cascading logic: Backfills deficits to hit the raw total
            short_target = int(quota * short_pct)
            medium_target = int(quota * medium_pct)
            long_target = quota - short_target - medium_target
            
            taken_short = min(short_target, len(buckets["short"]))
            lang_sampled.extend(buckets["short"][:taken_short])
            
            medium_target += (short_target - taken_short)
            taken_medium = min(medium_target, len(buckets["medium"]))
            lang_sampled.extend(buckets["medium"][:taken_medium])
            
            long_target += (medium_target - taken_medium)
            taken_long = min(long_target, len(buckets["long"]))
            lang_sampled.extend(buckets["long"][:taken_long])
            
            long_deficit = long_target - taken_long
            if long_deficit > 0:
                pool = buckets["short"][taken_short:] + buckets["medium"][taken_medium:]
                random.shuffle(pool)
                lang_sampled.extend(pool[:long_deficit])
            
        sampled_offsets.extend(lang_sampled)
        sample_stats["language_distribution"][lang] = len(lang_sampled)

    # Shuffle the final compiled dataset offsets so languages aren't clustered
    random.shuffle(sampled_offsets)

    # Re-open the file and extract exactly the samples we need (Pass 2)
    sampled_data = []
    with open(dataset_file, 'rb') as f:
        for offset in tqdm(sampled_offsets, desc="Extracting Selected Samples"):
            f.seek(offset)
            line = f.readline()
            sampled_data.append(json.loads(line.decode('utf-8')))

    # Write out data
    print(f"\nPreparing to write {len(sampled_data)} samples to disk...")
    with open(samples_file, 'w', encoding='utf-8') as f:
        for item in tqdm(sampled_data, desc="Saving Samples", unit="items"):
            # Drop the internal 'language' tag before saving so Hugging Face can read it normally
            clean_item = {"messages": item["messages"]}
            f.write(json.dumps(clean_item, ensure_ascii=False) + "\n")
            
            sample_stats["total_samples"] += 1
            
            # Update user stats for sample_summary.json
            try:
                # Determine bucket for final summary first to ensure it is always counted
                word_count = 0
                for msg in reversed(item["messages"]):
                    if msg["role"] == "assistant":
                        content_clean = re.sub(r'^\[.*?\]:\s*', '', msg["content"])
                        word_count = len(content_clean.split())
                        break
                        
                bucket = "long"
                if word_count <= short_max: bucket = "short"
                elif word_count <= medium_max: bucket = "medium"

                # Update global sums
                sample_stats["actual_length_totals"][bucket] += 1

                user_msg = item["messages"][1]["content"]
                username_match = re.match(r'^\[(.*?)\]:', user_msg)
                
                if username_match:
                    username = username_match.group(1)

                    if username not in sample_stats["actual_user_distribution"]:
                        sample_stats["actual_user_distribution"][username] = {
                            "total": 0, "short": 0, "medium": 0, "long": 0
                        }
                        
                    sample_stats["actual_user_distribution"][username]["total"] += 1
                    sample_stats["actual_user_distribution"][username][bucket] += 1
            except Exception:
                pass

    # Calculate actual percentage distribution for the summary
    total_extracted = sample_stats["total_samples"]
    if total_extracted > 0:
        sample_stats["actual_length_distribution_pct"]["short_pct"] = round(sample_stats["actual_length_totals"]["short"] / total_extracted, 4)
        sample_stats["actual_length_distribution_pct"]["medium_pct"] = round(sample_stats["actual_length_totals"]["medium"] / total_extracted, 4)
        sample_stats["actual_length_distribution_pct"]["long_pct"] = round(sample_stats["actual_length_totals"]["long"] / total_extracted, 4)

    sample_summary_file = os.path.join(output_dir, "sample_summary.json")
    with open(sample_summary_file, 'w', encoding='utf-8') as f:
        json.dump(sample_stats, f, indent=4)
        
    print(f"Sample summary written to {sample_summary_file}.")

    # Zipping Logic
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