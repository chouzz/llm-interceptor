#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path


def build_ui(watch: bool = False):
    """Build the React UI.

    Args:
        watch: If True, run Vite in watch mode (auto-rebuild on changes)
    """
    root_dir = Path(__file__).parent
    ui_dir = root_dir / "ui"

    # On Windows, npm is a batch script and requires shell=True
    use_shell = sys.platform == "win32"

    # Check if node_modules exists
    if not (ui_dir / "node_modules").exists():
        print("Installing dependencies...")
        subprocess.run(["npm", "install"], cwd=ui_dir, check=True, shell=use_shell)

    if watch:
        print("Starting Vite watch mode...")
        print("UI will auto-rebuild on changes. Press Ctrl+C to stop.")
        subprocess.run(
            ["npm", "run", "build", "--", "--watch"],
            cwd=ui_dir,
            check=True,
            shell=use_shell,
        )
    else:
        print("Building UI...")
        subprocess.run(
            ["npm", "run", "build"],
            cwd=ui_dir,
            check=True,
            shell=use_shell,
        )
        # Avoid emoji here to prevent UnicodeEncodeError on GBK consoles (e.g. Windows)
        print("UI built successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the UI")
    parser.add_argument(
        "--watch", "-w", action="store_true", help="Enable watch mode (auto-rebuild on changes)"
    )
    args = parser.parse_args()

    build_ui(watch=args.watch)
