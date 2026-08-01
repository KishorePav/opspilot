from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path("scripts/run_live_agent_eval.py")
    spec = importlib.util.spec_from_file_location("run_live_agent_eval", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiveEvaluationScriptTests(unittest.TestCase):
    def test_live_execution_requires_confirmation_and_runtime_key(self) -> None:
        module = _load_script()

        with self.assertRaisesRegex(ValueError, "confirm-live-api"):
            module.validate_live_execution(
                confirmed=False,
                api_key_present=True,
                model="gpt-5.6",
                max_cases=1,
            )
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            module.validate_live_execution(
                confirmed=True,
                api_key_present=False,
                model="gpt-5.6",
                max_cases=1,
            )

    def test_live_execution_rejects_unbounded_or_invalid_inputs(self) -> None:
        module = _load_script()

        with self.assertRaisesRegex(ValueError, "model name"):
            module.validate_live_execution(
                confirmed=True,
                api_key_present=True,
                model="gpt-5.6; echo unsafe",
                max_cases=1,
            )
        with self.assertRaisesRegex(ValueError, "max cases"):
            module.validate_live_execution(
                confirmed=True,
                api_key_present=True,
                model="gpt-5.6",
                max_cases=11,
            )


if __name__ == "__main__":
    unittest.main()
