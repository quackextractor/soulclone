import argparse
import sys
import logging
import os
import traceback


def setup_logging():
    """Sets up global console and file logging EARLY to catch import crashes."""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    c_handler = logging.StreamHandler()
    c_handler.setFormatter(formatter)
    logger.addHandler(c_handler)

    os.makedirs("out", exist_ok=True)
    f_handler = logging.FileHandler(os.path.join("out", "main.log"), mode='w', encoding='utf-8')
    f_handler.setFormatter(formatter)
    logger.addHandler(f_handler)


# Initialize logging immediately to catch fatal import errors
setup_logging()

try:
    import asyncio
    from dotenv import load_dotenv
    from src.preprocess import process_discord_logs
    from src.sampler import generate_samples
    from src.discord_bot import run_bot
    from src.updater import toggle_autoupdate_env, run_update, restart_process
except Exception:
    logging.error(f"CRITICAL FATAL ERROR DURING STARTUP:\n{traceback.format_exc()}")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Discord Persona: Unified CLI Tool\n\n"
            "Available Commands:\n"
            "  python main.py preprocess    # Run the local data pipeline\n"
            "  python main.py sample        # Extract a small jsonl sample\n"
            "  python main.py bot           # Run the local Discord bot\n"
            "  python main.py update        # Manually trigger an update check and pull\n"
            "  python main.py autoupdate    # Toggle background autoupdate in .env"
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

    # Command: bot
    subparsers.add_parser(
        "bot",
        help="Start the Discord bot connected to the local LM Studio model",
    )

    # Command: update
    subparsers.add_parser(
        "update",
        help="Manually trigger an update check and pull the latest release",
    )

    # Command: autoupdate
    autoupdate_parser = subparsers.add_parser(
        "autoupdate",
        help="Toggle background autoupdate in .env",
    )
    autoupdate_parser.add_argument("state", choices=["on", "off"], help="Enable or disable autoupdate")

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

    elif args.command == "bot":
        logging.info("Starting the Discord bot...")
        run_bot()

    elif args.command == "update":
        logging.info("Triggering update process...")
        load_dotenv()
        github_repo = os.getenv("GITHUB_REPO")

        async def log_cli(msg):
            logging.info(msg.replace("```\n", "").replace("\n```", ""))

        success = asyncio.run(run_update(github_repo, log_callback=log_cli))
        if success:
            logging.info("Update successful. Restarting...")
            restart_process()
        else:
            logging.error("Update failed.")

    elif args.command == "autoupdate":
        new_state = (args.state == "on")
        toggle_autoupdate_env(new_state)
        logging.info(f"Autoupdate set to {'ON' if new_state else 'OFF'} in .env")


if __name__ == "__main__":
    main()
