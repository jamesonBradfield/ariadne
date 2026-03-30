import sys
import subprocess
import os

def main():
    if len(sys.argv) < 3:
        print("Usage: python run_python_tests.py <target_file> <test_contract>")
        sys.exit(1)

    target_file = sys.argv[1]
    test_contract = sys.argv[2]

    with open(target_file, "r", encoding="utf-8") as f:
        source_code = f.read()

    with open(test_contract, "r", encoding="utf-8") as f:
        test_code = f.read()

    combined_code = source_code + "\n\n" + test_code

    temp_file = "ariadne_temp_test.py"
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(combined_code)

    # Use pytest to run the temp file
    res = subprocess.run([sys.executable, "-m", "pytest", temp_file], capture_output=True, text=True)

    print(res.stdout)
    if res.stderr:
        print(res.stderr)

    sys.exit(res.returncode)

if __name__ == "__main__":
    main()
