import sys
import subprocess
import os
import shutil
from pathlib import Path


def find_project_root(target_file: str) -> Path:
    current = Path(target_file).parent
    while current != current.parent:
        if (current / "pyproject.toml").exists() or (current / "setup.py").exists():
            return current
        current = current.parent
    return Path(target_file).parent


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: python run_sandboxed_python_tests.py <target_file> <test_contract>"
        )
        sys.exit(1)

    target_file = sys.argv[1]
    test_contract = sys.argv[2]

    project_root = find_project_root(target_file)
    if not project_root:
        project_root = Path(target_file).parent

    tests_dir = project_root / "tests"
    tests_dir.mkdir(exist_ok=True)

    test_file_path = tests_dir / "ariadne_sandboxed_test.py"

    with open(test_contract, "r", encoding="utf-8") as f:
        test_code = f.read()

    with open(test_file_path, "w", encoding="utf-8") as f:
        f.write(test_code)

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_file_path), "-v"],
            cwd=project_root,
            capture_output=True,
            text=True,
        )

        print(result.stdout)
        if result.stderr:
            print(result.stderr)

        sys.exit(result.returncode)
    finally:
        if test_file_path.exists():
            test_file_path.unlink()


if __name__ == "__main__":
    main()
