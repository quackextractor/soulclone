import os
import yaml
import urllib.request
import concurrent.futures
from huggingface_hub import snapshot_download
from tqdm import tqdm


class TqdmUpTo(tqdm):
    """Helper class to provide a progress bar for standard urlretrieve downloads."""

    def update_to(self, b=1, bsize=1, tsize=None):
        if tsize is not None:
            self.total = tsize
        self.update(b * bsize - self.n)


def download_chunk(url, start, end, temp_file, pbar):
    """Downloads a specific byte range of a file and updates the shared progress bar."""
    req = urllib.request.Request(url, headers={'Range': f'bytes={start}-{end}'})
    with urllib.request.urlopen(req) as response:
        with open(temp_file, "wb") as f:
            while True:
                # Stream in 8KB blocks to prevent RAM spikes
                chunk = response.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                pbar.update(len(chunk))
    return temp_file


def fast_isolated_download(url, output_dir, output_file, config):
    """Native Python parallel downloader ensuring 100 percent isolation with progress tracking."""
    os.makedirs(output_dir, exist_ok=True)
    target_path = os.path.join(output_dir, output_file)

    if os.path.exists(target_path):
        print(f"{output_file} already exists at {target_path}. Skipping download.")
        return True

    connections = int(config.get("downloads", {}).get("parallel_connections", 16))

    try:
        req = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(req) as response:
            content_length = response.headers.get('Content-Length')
            accept_ranges = response.headers.get('Accept-Ranges')

        if not content_length or accept_ranges != 'bytes':
            print("Server does not support parallel chunking. Falling back to standard stream.")
            with TqdmUpTo(unit='B', unit_scale=True, unit_divisor=1024, miniters=1, desc=output_file) as t:
                urllib.request.urlretrieve(url, target_path, reporthook=t.update_to)
            return True

        total_size = int(content_length)
        chunk_size = total_size // connections

        print(f"Starting parallel download: {connections} connections for {total_size} bytes.")

        futures = []
        temp_files = []

        # Initialize the global progress bar
        with tqdm(total=total_size, unit='B', unit_scale=True, unit_divisor=1024, desc=output_file) as pbar:
            with concurrent.futures.ThreadPoolExecutor(max_workers=connections) as executor:
                for i in range(connections):
                    start = i * chunk_size
                    end = start + chunk_size - 1 if i < connections - 1 else total_size - 1
                    temp_file = f"{target_path}.part{i}"
                    temp_files.append(temp_file)
                    futures.append(executor.submit(download_chunk, url, start, end, temp_file, pbar))

                concurrent.futures.wait(futures)

        print("Merging file chunks...")
        with open(target_path, "wb") as outfile:
            for temp_file in temp_files:
                with open(temp_file, "rb") as infile:
                    outfile.write(infile.read())
                os.remove(temp_file)

        return True

    except Exception as e:
        print(f"Parallel download failed: {e}. Falling back to standard stream.")
        with TqdmUpTo(unit='B', unit_scale=True, unit_divisor=1024, miniters=1, desc=output_file) as t:
            urllib.request.urlretrieve(url, target_path, reporthook=t.update_to)
        return True


def run_downloads(args):
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    os.makedirs("models", exist_ok=True)

    if getattr(args, "embedding", False) or getattr(args, "all", False):
        print("Downloading embedding model...")
        repo_id = config.get("downloads", {}).get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2")
        target_dir = os.path.join("models", repo_id.split("/")[-1])
        snapshot_download(repo_id=repo_id, local_dir=target_dir)
        print("Embedding model downloaded successfully.")

    if getattr(args, "llamafile", False) or getattr(args, "all", False):
        lf_url = config.get("downloads", {}).get("llamafile_url")

        if not lf_url:
            print("Missing llamafile_url in config.yaml.")
            return

        exe_name = "llamafile.exe" if os.name == 'nt' else "llamafile"

        print(f"Fetching standalone llamafile to models/{exe_name}...")
        success = fast_isolated_download(lf_url, "models", exe_name, config)

        if success:
            if os.name != 'nt':
                exe_path = os.path.join("models", exe_name)
                print("Granting execution permissions to Linux binary...")
                os.chmod(exe_path, 0o755)

            print("Llamafile downloaded successfully.")
            print("Note: Ensure your configured .gguf model file is placed in the 'models' directory manually.")
