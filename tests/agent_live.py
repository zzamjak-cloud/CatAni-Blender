"""기존 로그인된 Codex CLI에서 실제 전신 동작 명세를 생성한다."""
import importlib
import json
from pathlib import Path
import sys
import time
import types

root = Path(__file__).resolve().parents[1]
package = types.ModuleType("catani")
package.__path__ = [str(root / "catani")]
sys.modules["catani"] = package
bridge = importlib.import_module("catani.agent_bridge")
refine = "--refine" in sys.argv
previous = json.loads((root / "artifacts/Agent_Natural_Wave_Plan.json").read_text()) if refine else None
prompt = ("현재 명세에서 팔 올리기를 5도 낮추고 몸통 회전을 2도 줄여줘. 다른 값은 그대로 유지해줘." if refine else
          "친구에게 오른손으로 자연스럽게 두 번 인사해 줘. 전체 3.5초. 먼저 상대를 보고, "
          "한쪽 다리로 무게를 옮기고, 몸통과 어깨가 팔보다 먼저 준비하고 팔을 내린 뒤 몸이 늦게 안정되게 해줘. "
          "과장하지 말고 친근한 느낌으로.")
job = bridge.AgentJob(prompt, previous_plan=previous)
try:
    while True:
        plan = job.poll()
        if plan is not None:
            assert plan["supported"]
            assert plan["side"] == "R" and plan["repeat"] == 2
            if refine:
                assert plan["arm_lift"] == previous["arm_lift"] - 5
                assert plan["torso_turn"] == previous["torso_turn"] - 2
            filename = "Agent_Refined_Natural_Wave_Plan.json" if refine else "Agent_Natural_Wave_Plan.json"
            target = root / "artifacts" / filename
            target.write_text(json.dumps(plan, ensure_ascii=False, indent=2)+"\n")
            print("CATANI_AGENT_LIVE", json.dumps(plan, ensure_ascii=False), flush=True)
            break
        time.sleep(0.25)
finally:
    job.close()
