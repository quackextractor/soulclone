import argparse
import sys
import logging

from src.preprocess import process_discord_logs
from src.sampler import generate_samples

def setup_logging():
    """Sets up global console logging.""" #
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    c_handler = logging.StreamHandler()
    c_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(c_handler)

def main():
    setup_logging()

    parser = argparse.ArgumentParser(
        description=(
            "Lustsoul Discord Persona - Unified CLI Tool\n\n" #
            "Available Commands:\n"
            "  python main.py preprocess    # Run the local data pipeline\n"
            "  python main.py sample        # Extract a small jsonl sample"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands") #
    subparsers.required = True

    # Command: preprocess
    subparsers.add_parser(
        "preprocess",
        help="Process raw Discord CSV exports into a fine-tuning dataset JSONL file", #
    )

    # Command: sample
    subparsers.add_parser(
        "sample",
        help="Extract a small, token-safe JSONL sample from source files for debugging",
    )

    # Check if no arguments were passed, print help and exit
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    if args.command == "preprocess":
        logging.info("Starting local preprocessing pipeline...")
        process_discord_logs()
    elif args.command == "sample":
        logging.info("Generating data samples...")
        generate_samples()

if __name__ == "__main__":
    main()