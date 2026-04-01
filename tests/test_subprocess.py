import pytest
from ariadne.components import SubprocessSensor

def test_subprocess_sensor_success():
    # Test with a simple command that should succeed
    sensor = SubprocessSensor(["echo", "Hello World"])
    result = sensor.execute()
    assert result['success']
    assert "Hello World" in result['stdout']
    assert result['returncode'] == 0

def test_subprocess_sensor_fail():
    # Test with a command that should fail
    # Note: 'false' might not be on Windows, so use a non-existent command
    sensor_fail = SubprocessSensor(["cmd", "/c", "exit 1"])
    result_fail = sensor_fail.execute()
    assert not result_fail['success']
    assert result_fail['returncode'] != 0
