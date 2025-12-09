#!/usr/bin/env python3
import os
import shutil
import subprocess
from pathlib import Path

def build_ui():
    """Build the React UI and copy assets to the Python package."""
    root_dir = Path(__file__).parent
    ui_dir = root_dir / "ui"
    static_dir = root_dir / "src" / "cci" / "static"

    print(f"Building UI in {ui_dir}...")
    
    # Check if node_modules exists
    if not (ui_dir / "node_modules").exists():
        print("Installing dependencies...")
        subprocess.run(["npm", "install"], cwd=ui_dir, check=True)

    # Build the React app
    print("Running npm run build...")
    subprocess.run(["npm", "run", "build"], cwd=ui_dir, check=True)

    # Clean destination
    if static_dir.exists():
        print(f"Cleaning {static_dir}...")
        shutil.rmtree(static_dir)
    
    # Copy assets
    dist_dir = ui_dir / "dist"
    print(f"Copying {dist_dir} to {static_dir}...")
    shutil.copytree(dist_dir, static_dir)
    
    print("✅ UI built and installed successfully.")

if __name__ == "__main__":
    build_ui()

