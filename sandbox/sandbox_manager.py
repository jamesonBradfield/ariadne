import sys
import os
import shutil
from pathlib import Path


def setup_sandbox():
    sandbox_dir = Path(__file__).parent
    clean_dir = sandbox_dir / "clean"
    working_dir = sandbox_dir / "working"
    templates_dir = sandbox_dir / "templates"

    clean_dir.mkdir(exist_ok=True)
    working_dir.mkdir(exist_ok=True)
    templates_dir.mkdir(exist_ok=True)

    for template_file in templates_dir.glob("*.py"):
        target_file = working_dir / template_file.name
        shutil.copy2(template_file, target_file)
        print(f"Copied {template_file.name} to working directory")

    print(f"Sandbox setup complete. Working directory: {working_dir}")
    return working_dir


def teardown_sandbox():
    sandbox_dir = Path(__file__).parent
    working_dir = sandbox_dir / "working"

    if working_dir.exists():
        for file in working_dir.glob("*.py"):
            file.unlink()
        print("Sandbox cleaned up")
    else:
        print("No sandbox to clean up")


def get_working_file(filename: str) -> Path:
    return Path(__file__).parent / "working" / filename


def get_clean_file(filename: str) -> Path:
    return Path(__file__).parent / "clean" / filename


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sandbox environment manager")
    parser.add_argument(
        "command", choices=["setup", "teardown", "get"], help="Command to run"
    )
    parser.add_argument("--file", help="File name for get command")
    args = parser.parse_args()

    if args.command == "setup":
        setup_sandbox()
    elif args.command == "teardown":
        teardown_sandbox()
    elif args.command == "get":
        if not args.file:
            print("Error: --file required for get command")
            sys.exit(1)
        file_path = get_working_file(args.file)
        print(file_path)
