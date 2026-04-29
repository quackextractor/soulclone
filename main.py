import argparse
import sys
import logging
import os
import subprocess
import yaml

from src.preprocess import process_discord_logs
from src.sampler import generate_samples
from src.bot.core import run_bot


def setup_logging():
    """Sets up global console logging."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    c_handler = logging.StreamHandler()
    c_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(c_handler)


def main():
    setup_logging()

    parser = argparse.ArgumentParser(
        description=(
            "Discord Persona: Unified CLI Tool\n\n"
            "Available Commands:\n"
            "  python main.py preprocess    # Run the local data pipeline\n"
            "  python main.py sample        # Extract a small jsonl sample\n"
            "  python main.py download      # Download models and binaries\n"
            "  python main.py bot           # Run the local Discord bot"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    subparsers.required = True

    # Command: preprocess
    preprocess_parser = subparsers.add_parser(
        "preprocess",
        help="Process raw Discord CSV exports into a fine-tuning dataset JSONL file",
    )
    preprocess_parser.add_argument(
        "--sample",
        action="store_true",
        help="Run the sampling script immediately after preprocessing",
    )

    # Command: sample
    subparsers.add_parser(
        "sample",
        help="Extract a small, token-safe JSONL sample from source files for debugging",
    )

    # Command: download
    download_parser = subparsers.add_parser(
        "download",
        help="Download standalone models and binaries"
    )
    download_parser.add_argument("--embedding", action="store_true", help="Download embedding model")
    download_parser.add_argument("--llamafile", action="store_true", help="Download standalone llamafile")
    download_parser.add_argument("--all", action="store_true", help="Download all configured binaries and models")

    # Command: bot
    bot_parser = subparsers.add_parser(
        "bot",
        help="Start the Discord bot connected to the local LM Studio model",
    )
    bot_parser.add_argument("--llamafile", action="store_true", help="Run the configured llamafile in the background")

    # Check if no arguments were passed, print help and exit
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    if args.command == "preprocess":
        logging.info("Starting local preprocessing pipeline...")
        process_discord_logs()

        if args.sample:
            logging.info("Generating data samples...")
            generate_samples()

    elif args.command == "sample":
        logging.info("Generating data samples...")
        generate_samples()

    elif args.command == "download":
        from src.downloader import run_downloads
        run_downloads(args)

    elif args.command == "bot":
        llamafile_process = None
        if getattr(args, "llamafile", False):
            with open("config.yaml", "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            exe_name = "llamafile.exe" if os.name == 'nt' else "./llamafile"
            gguf_name = config.get("downloads", {}).get("local_gguf_name", "model.gguf")
            lf_args = config.get("downloads", {}).get("llamafile_args", [])

            exe_path = os.path.abspath(os.path.join("models", exe_name.replace("./", "")))
            gguf_path = os.path.abspath(os.path.join("models", gguf_name))

            if not os.path.exists(exe_path):
                logging.error("Llamafile executable missing. Run 'python main.py download --llamafile' first.")
                sys.exit(1)

            if not os.path.exists(gguf_path):
                logging.error(f"GGUF model missing. Please manually place '{gguf_name}' into the 'models/' directory.")
                sys.exit(1)

            logging.info("Starting local Llamafile server...")

            command = [exe_path, "-m", gguf_name] + lf_args
            if os.name != 'nt':
                command = ["sh"] + command
            llamafile_process = subprocess.Popen(command, cwd="models")

        logging.info("Starting the Discord bot...")
        try:
            run_bot(llamafile_process)
        finally:
            if llamafile_process:
                logging.info("Terminating Llamafile server...")
                llamafile_process.terminate()


if __name__ == "__main__":
    main()
