import os
import json
import random
import yaml
from dotenv import load_dotenv

from src.preprocess import extract_pairs_from_csv

def generate_samples():
    load_dotenv()
    source_dir = os.getenv("SOURCE_DIR")

    if not source_dir:
        print("Error: SOURCE_DIR not found in .env file.")
        return

    # Load configuration
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    output_dir = config["directories"]["output"]
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, config["files"]["samples"])

    csv_files = []
    for root, dirs, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".csv"):
                csv_files.append(os.path.join(root, file))
    
    if not csv_files:
        print("No CSV files found.")
        return

    target_total_samples = config["sampling"]["target_total_samples"]
    samples_per_file = max(1, target_total_samples // len(csv_files))

    dataset = []

    for filepath in csv_files:
        # Pull the pre-cleaned data directly from our main pipeline
        file_samples = extract_pairs_from_csv(filepath)

        if len(file_samples) > samples_per_file:
            dataset.extend(random.sample(file_samples, samples_per_file))
        else:
            dataset.extend(file_samples)

    with open(output_file, 'w', encoding='utf-8') as f:
        for entry in dataset:
            f.write(json.dumps(entry) + "\n")

    print(f"Sampling complete. {len(dataset)} context pairs saved to {output_file}.")

if __name__ == "__main__":
    generate_samples()