"""외부 호출 없이 명세 검증과 에이전트 프로세스 경계를 검사한다."""
import importlib
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

root = Path(__file__).resolve().parents[1]
package = types.ModuleType("catani")
package.__path__ = [str(root / "catani")]
sys.modules["catani"] = package
plans = importlib.import_module("catani.agent_plan")
bridge = importlib.import_module("catani.agent_bridge")


class AgentBoundaryTests(unittest.TestCase):
    def test_reject_invalid_plans(self):
        for changes in ({"duration":True}, {"weight_shift":float("nan")},
                        {"arm_lift":500}, {"repeat":2.5}, {"execute":"os.system('x')"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                plans.validate_plan(dict(plans.DEFAULT_PLAN, **changes))
        text = json.dumps(plans.DEFAULT_PLAN)
        with self.assertRaises(ValueError):
            plans.parse_plan(text[:-1]+', "side":"L"}')
        with self.assertRaises(ValueError):
            plans.parse_plan("x"*16385)

    @patch.object(bridge.subprocess, "Popen")
    @patch.object(bridge, "find_codex", return_value="/safe/codex")
    def test_pending_result_and_isolation(self, finder, popen):
        process = MagicMock()
        process.poll.return_value = None
        popen.return_value = process
        with patch.dict(bridge.os.environ, {"OPENAI_API_KEY":"test-secret"}):
            job = bridge.AgentJob("오른손 인사")
        self.assertIsNone(job.poll())
        args, kwargs = popen.call_args
        self.assertIsInstance(args[0], list)
        self.assertFalse(kwargs.get("shell", False))
        self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
        self.assertIn("read-only", args[0])
        self.assertIn("--ignore-user-config", args[0])
        self.assertNotIn(str(root / "Blender"), " ".join(args[0]))
        job.result_path.write_text(json.dumps(plans.DEFAULT_PLAN))
        directory = job.directory
        process.poll.return_value = 0
        self.assertEqual(job.poll(), plans.DEFAULT_PLAN)
        self.assertFalse(directory.exists())

    @patch.object(bridge.os, "killpg", create=True)
    @patch.object(bridge.subprocess, "Popen")
    @patch.object(bridge, "find_codex", return_value="/safe/codex")
    def test_timeout_and_cleanup(self, finder, popen, kill):
        process = MagicMock()
        process.poll.return_value = None
        popen.return_value = process
        job = bridge.AgentJob("인사", timeout=-1)
        directory = job.directory
        with self.assertRaises(TimeoutError):
            job.poll()
        self.assertFalse(directory.exists())
        if bridge.os.name != "nt":
            kill.assert_called()


if __name__ == "__main__":
    unittest.main()
