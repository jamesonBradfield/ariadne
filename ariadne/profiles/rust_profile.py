import tree_sitter
from ariadne.components import SubprocessSensor
import json
from typing import Dict, Any


class CargoCheckHook:
    """
    Extends the subprocess sensor to run cargo check --message-format=json and parse the output.
    """

    def __init__(self, working_dir: str = "."):
        self.sensor = SubprocessSensor(["cargo", "check", "--message-format=json"])
        self.working_dir = working_dir

    def execute(self) -> Dict[str, Any]:
        """
        Run cargo check and parse JSON output into a clean dictionary.

        Returns:
            Dictionary with keys: success (bool), messages (List[Dict]), errors (List[str])
        """
        result = self.sensor.execute()

        if not result["success"]:
            return {
                "success": False,
                "messages": [],
                "errors": [result["stderr"]] if result["stderr"] else ["Unknown error"],
                "raw_output": result,
            }

        # Parse JSON lines output
        messages = []
        errors = []

        for line in result["stdout"].strip().split("\n"):
            if not line:
                continue
            try:
                message = json.loads(line)
                messages.append(message)
                # Collect error messages
                if (
                    message.get("reason") == "compiler-message"
                    and message.get("message", {}).get("level") == "error"
                ):
                    msg_data = message.get("message", {})
                    errors.append(
                        {
                            "message": msg_data.get("message", ""),
                            "code": msg_data.get("code", {}).get("code")
                            if msg_data.get("code")
                            else None,
                            "span": msg_data.get("spans", [{}])[0]
                            if msg_data.get("spans")
                            else {},
                        }
                    )
            except json.JSONDecodeError:
                # Skip non-JSON lines
                continue

        return {
            "success": len(errors) == 0,
            "messages": messages,
            "errors": errors,
            "raw_output": result,
        }


class AutoFixerActuator:
    """
    A component that runs cargo clippy --fix --allow-dirty and rustfmt to automatically heal formatting.
    """

    def __init__(self):
        self.clippy_fix_sensor = SubprocessSensor(
            ["cargo", "clippy", "--fix", "--allow-dirty"]
        )
        self.rustfmt_sensor = SubprocessSensor(["rustfmt"])

    def execute(self) -> Dict[str, Any]:
        """
        Run auto-fixing tools.

        Returns:
            Dictionary with success status and outputs from both tools
        """
        # Run clippy fix first
        clippy_result = self.clippy_fix_sensor.execute()

        # Then run rustfmt
        rustfmt_result = self.rustfmt_sensor.execute()

        return {
            "success": clippy_result["success"] and rustfmt_result["success"],
            "clippy": clippy_result,
            "rustfmt": rustfmt_result,
        }
