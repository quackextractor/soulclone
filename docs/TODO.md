### 1. Data Quality
The "Lazy LLM" Problem Your samples contain a lot of highly authentic, but very short responses like "xd" , "Jj" , and "yes". While this perfectly captures the real Discord experience, LLMs are incredibly prone to "length collapse" during fine-tuning. If 30% of your dataset is 1-2 word answers, the model will learn that the easiest way to minimize loss is to almost *always* give 1-2 word answers.
* **The Fix:** Consider adding a "length penalty" or downsampling mechanism in `extract_pairs_from_csv`. You don't want to remove short answers completely, but you might want to randomly drop 50-70% of responses that are under 3 words so the model is forced to learn your longer, more complex sentence structures.

### 2. Logic Bug: The Sampler Output Count You set your `target_total_samples` to 100 in `config.yaml` , but the output generated 131 samples.
* **The Cause:** In `src/sampler.py`, your math is `samples_per_file = max(1, target_total_samples // len(csv_files))`. Because you have more than 100 CSV files (implied by the math), it defaults to pulling 1 sample per file, causing it to overshoot your target.
* **The Fix:** Instead of sampling per file, you should gather all the lines into a list and use `random.sample(all_lines, target_total_samples)`.

### 3. Script Efficiency: Redundant Processing Currently, your `src/sampler.py` script re-runs `extract_pairs_from_csv(filepath)` on the raw data every time you want to generate a sample.
* **The Fix:** Since `preprocess` already creates the fully cleaned `processed/dataset.jsonl`, your sampler should just open that JSONL file, read the lines, and grab a random selection. This will turn your sampling time from minutes (re-parsing 47k lines) into milliseconds.

### 4. Multilingual Model Selection 
I see from your dataset that your persona frequently switches between English , Czech , and German. This is awesome, but smaller models (like a standard Llama-3-8B ) can sometimes struggle with seamless code-switching and might reply in the wrong language if the context isn't perfectly clear. Make sure whatever base model you choose was heavily trained on multilingual data (Mistral and Cohere models usually excel at this out-of-the-box).