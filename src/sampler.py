import os
import random
import yaml

def generate_samples():
    # Load configuration
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    output_dir = config["directories"]["output"]
    dataset_file = os.path.join(output_dir, config["files"]["dataset"])
    samples_file = os.path.join(output_dir, config["files"]["samples"])
    target_total_samples = config["sampling"]["target_total_samples"]

    if not os.path.exists(dataset_file):
        print(f"Error: {dataset_file} not found. Please run 'preprocess' first to generate the dataset.")
        return

    # Read preprocessed lines directly
    with open(dataset_file, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()

    if not all_lines:
        print("Error: The dataset file is empty.")
        return

    # Gather random samples based on total limit, guaranteeing exact target length
    sample_size = min(target_total_samples, len(all_lines))
    sampled_lines = random.sample(all_lines, sample_size)

    # Save to samples file
    with open(samples_file, 'w', encoding='utf-8') as f:
        for line in sampled_lines:
            f.write(line)

    print(f"Sampling complete. {len(sampled_lines)} context pairs saved to {samples_file}.")

if __name__ == "__main__":
    generate_samples()