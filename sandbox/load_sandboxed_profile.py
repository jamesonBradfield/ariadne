import sys
import os
import json
from pathlib import Path


def load_sandboxed_profile():
    profile_path = Path(__file__).parent / "sandboxed_python_profile.json"

    if not profile_path.exists():
        print(f"Error: Profile not found at {profile_path}")
        sys.exit(1)

    with open(profile_path, "r") as f:
        config = json.load(f)

    return config


if __name__ == "__main__":
    profile = load_sandboxed_profile()
    print(json.dumps(profile, indent=2))
