import os
import subprocess
import sys

# Set environment variable
os.environ["ARIADNE_AUTO_ACCEPT"] = "true"

# Define the command
cmd = [
    "./.venv/Scripts/python",
    "engine.py",
    "--project-dir", "C:/Users/jamie/projects/Godot/TexelSplatting/.rust",
    "--targets", "C:/Users/jamie/projects/Godot/TexelSplatting/.rust/src/realtime_probe.rs",
    "--intent", "Implement a method get_total_cameras in RealtimeProbe that returns self.cameras.len() as an i32. Use the #[func] attribute.",
    "--profile", "rust",
    "--headless",
    "--max-turns", "40"
]

# Run the process
result = subprocess.run(cmd)
sys.exit(result.returncode)
