"""Independent verifier process. Executing Python still requires trusted code/container."""
import importlib.util
import builtins
import json
import math
import sys
from pathlib import Path


def check(workspace, contract):
    spec = importlib.util.spec_from_file_location("audited_app", workspace / "app.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(workspace))
    spec.loader.exec_module(module)
    function = getattr(module, contract["function"])
    for case in contract["cases"]:
        if "raises" in case:
            try:
                function(*case["args"], **case.get("kwargs", {}))
            except Exception as exc:
                expected_type = getattr(builtins, case["raises"], None)
                if not isinstance(expected_type, type) or not isinstance(exc, expected_type):
                    raise AssertionError(f"Expected {case['raises']}, got {type(exc).__name__}")
            else:
                raise AssertionError("Expected exception was not raised")
        else:
            result = function(*case["args"], **case.get("kwargs", {}))
            expected = case["expected"]
            equal = math.isclose(result, expected, rel_tol=1e-8, abs_tol=1e-8) if isinstance(expected, float) else result == expected
            if not equal:
                raise AssertionError(f"Input {case['args']}: expected {expected!r}, got {result!r}")


if __name__ == "__main__":
    check(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
    print("Independent verifier passed")
