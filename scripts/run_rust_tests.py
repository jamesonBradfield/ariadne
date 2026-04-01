import sys
import subprocess
import os
import shutil

def find_cargo_toml(path):
    current = os.path.dirname(os.path.abspath(path))
    while current != os.path.dirname(current):
        if os.path.exists(os.path.join(current, "Cargo.toml")):
            return current
        current = os.path.dirname(current)
    return None

def main():
    if len(sys.argv) < 3:
        print("Usage: python run_rust_tests.py <target_file> <test_contract>")
        sys.exit(1)

    target_file = sys.argv[1]
    test_contract = sys.argv[2]

    # Find project root
    project_root = find_cargo_toml(target_file)
    if not project_root:
        # Fallback to standalone rustc for simple scripts
        print("No Cargo.toml found. Falling back to rustc...")
        with open(target_file, "r", encoding="utf-8") as f:
            source_code = f.read()
        with open(test_contract, "r", encoding="utf-8") as f:
            test_code = f.read()
        combined_code = source_code + "\n\n" + test_code
        temp_file = "ariadne_temp_test.rs"
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(combined_code)
        compile_res = subprocess.run(["rustc", "--test", temp_file], capture_output=True, text=True)
        if compile_res.returncode != 0:
            print("COMPILATION ERROR:\n" + compile_res.stderr)
            sys.exit(compile_res.returncode)
        exe_name = "ariadne_temp_test.exe" if os.name == "nt" else "./ariadne_temp_test"
        run_res = subprocess.run([exe_name], capture_output=True, text=True)
        print(run_res.stdout)
        if run_res.stderr: print(run_res.stderr)
        sys.exit(run_res.returncode)

    print(f"Project root found at: {project_root}")
    
    # Create a temporary test file in the project
    tests_dir = os.path.join(project_root, "tests")
    if not os.path.exists(tests_dir):
        os.makedirs(tests_dir)
    
    test_file_path = os.path.join(tests_dir, "ariadne_integration_test.rs")
    
    # We need to wrap the test code with necessary imports or mods
    # For ariadne, we usually just append the test contract
    # But for cargo tests, it might need 'use crate::*;' etc.
    with open(test_contract, "r", encoding="utf-8") as f:
        test_code = f.read()
    
    # Inject 'use crate::*;' to allow tests to see internal symbols if they are in the same crate
    # This is a heuristic.
    if "use godot::prelude::*;" not in test_code:
        test_code = "use godot::prelude::*;\n" + test_code

    with open(test_file_path, "w", encoding="utf-8") as f:
        f.write(test_code)

    try:
        # Run cargo test (which also performs cargo check)
        # We use --no-run first to capture compilation errors clearly
        print("Running cargo test --no-run...")
        compile_res = subprocess.run(
            ["cargo", "test", "--no-run"],
            cwd=project_root,
            capture_output=True,
            text=True
        )

        if compile_res.returncode != 0:
            print("COMPILATION ERROR:\n" + compile_res.stderr)
            sys.exit(compile_res.returncode)

        # If compilation passed, attempt to run
        print("Compilation successful. Running cargo test...")
        run_res = subprocess.run(
            ["cargo", "test"],
            cwd=project_root,
            capture_output=True,
            text=True
        )
        
        print(run_res.stdout)
        if run_res.stderr:
            print(run_res.stderr)
        
        sys.exit(run_res.returncode)
    finally:
        # Cleanup
        if os.path.exists(test_file_path):
            os.remove(test_file_path)

if __name__ == "__main__":
    main()
