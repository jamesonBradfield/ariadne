from components import SubprocessSensor


def test_subprocess_sensor():
    # Test with a simple command that should succeed
    sensor = SubprocessSensor(["echo", "Hello World"])
    result = sensor.execute()

    print("SubprocessSensor test (echo):")
    print(f"Success: {result['success']}")
    print(f"Stdout: '{result['stdout'].strip()}'")
    print(f"Stderr: '{result['stderr']}'")
    print(f"Return code: {result['returncode']}")

    # Test with a command that should fail
    sensor_fail = SubprocessSensor(["false"])  # 'false' command always returns 1
    result_fail = sensor_fail.execute()

    print("\nSubprocessSensor test (false):")
    print(f"Success: {result_fail['success']}")
    print(f"Stdout: '{result_fail['stdout']}'")
    print(f"Stderr: '{result_fail['stderr']}'")
    print(f"Return code: {result_fail['returncode']}")

    # Both should have executed without throwing exceptions
    return result["success"] and not result_fail["success"]


if __name__ == "__main__":
    success = test_subprocess_sensor()
    print(f"\nAll tests passed: {success}")
