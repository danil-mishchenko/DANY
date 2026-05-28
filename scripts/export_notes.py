# -*- coding: utf-8 -*-
"""CLI script to export Notion notes."""
import os
import sys

# Try to load .env file manually to avoid extra dependencies
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(root_dir, ".env")
if os.path.exists(env_path):
    with open(env_path, "r") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                key, value = line.strip().split("=", 1)
                os.environ[key] = value

# Add the project root and api directory to sys.path to allow absolute and relative imports
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)
sys.path.append(os.path.join(root_dir, "api"))

from api.services.export_service import export_to_file

if __name__ == "__main__":
    output_filename = "all_notes.md"
    print("--- DANY Notion Export Tool ---")
    try:
        export_to_file(output_filename)
        print(f"--- Export complete! File saved as: {output_filename} ---")
    except Exception as e:
        print(f"--- FAILED EXPORT: {e} ---")
