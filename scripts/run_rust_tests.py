import sys
import subprocess
import os

def main():
    if len(sys.argv) < 3:
        print("Usage: python run_rust_tests.py <target_file> <test_contract>")
        sys.exit(1)

    target_file = sys.argv[1]
    test_contract = sys.argv[2]

    # Combine the source and the tests
    with open(target_file, "r", encoding="utf-8") as f:
        source_code = f.read()

    with open(test_contract, "r", encoding="utf-8") as f:
        test_code = f.read()

    combined_code = source_code + "\n\n" + test_code

    temp_file = "ariadne_temp_test.rs"
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(combined_code)

    # Compile the tests
    compile_res = subprocess.run(
        ["rustc", "--test", temp_file], capture_output=True, text=True
    )

    if compile_res.returncode != 0:
        print("COMPILATION ERROR:\n" + compile_res.stderr)
        sys.exit(compile_res.returncode)

    # Run the tests
    exe_name = "ariadne_temp_test.exe" if os.name == "nt" else "./ariadne_temp_test"
    run_res = subprocess.run([exe_name], capture_output=True, text=True)

    print(run_res.stdout)
    if run_res.stderr:
        print(run_res.stderr)

    sys.exit(run_res.returncode)

if __name__ == "__main__":
    main()
