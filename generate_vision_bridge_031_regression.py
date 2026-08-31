"""Генерує окрему GPS-denied регресію для vision_bridge 0.3.1."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "configurations" / "gps-denied"
OUTPUT = ROOT / "configurations" / "vision-bridge-0.3.1-regression"
SUITES = ROOT / "suites"
ISSUE = "https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/3"
COORDINATION_ISSUE = "https://github.com/Drone-Age/ENV_DEV_NEO_SIM1/issues/15"


def load(name: str) -> dict:
    return json.loads((SOURCE / name).read_text(encoding="utf-8"))


def write_profile(source: str, configuration_id: str, seed: int) -> str:
    profile = copy.deepcopy(load(source))
    profile["configuration_id"] = configuration_id
    profile["description"] = (
        f"Окрема GPS-denied регресія vision_bridge 0.3.1, "
        f"режим {profile['pose_graph']['mode']}, висота 150 м, seed {seed}"
    )
    profile["wind"]["seed"] = seed
    profile["governance"] = {
        "issue": ISSUE,
        "coordination_issue": COORDINATION_ISSUE,
    }
    profile["runtime_requirements"]["vio_stack"] = {
        "version": "1.2.4",
        "source_commit": "6f822dd6f637c3ca3ce73bcc6b6973b28feebbce",
        "vision_bridge_version": "0.3.1",
    }
    path = OUTPUT / f"{configuration_id}.json"
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"../configurations/vision-bridge-0.3.1-regression/{path.name}"


def suite(suite_id: str, display_name: str, runs: list[dict], *, continue_on_fail: bool) -> None:
    document = {
        "schema": 1,
        "suite_id": suite_id,
        "display_name": display_name,
        "continue_on_fail": continue_on_fail,
        "navigation_mode": "gps_denied",
        "issue": ISSUE,
        "coordination_issue": COORDINATION_ISSUE,
        "runtime_requirements": {
            "ardupilot": {
                "product": "ArduCopter",
                "version": "4.7.0",
                "source_commit": "1511f27194f1dcc3728270883047bdf022b3fd53",
            },
            "vio_stack": {
                "version": "1.2.4",
                "source_commit": "6f822dd6f637c3ca3ce73bcc6b6973b28feebbce",
                "vision_bridge_version": "0.3.1",
            },
        },
        "consolidator": "consolidate_gps_denied_campaign.py",
        "runs": runs,
    }
    (SUITES / f"{suite_id}.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    smoke_id = "vb031-gps-denied-smoke-loop-and-map-reuse-s6599"
    smoke_path = write_profile(
        "gps-denied-smoke-loop_and_map_reuse-s6499.json", smoke_id, 6599
    )
    suite(
        "vision-bridge-0.3.1-gps-denied-smoke",
        "Engineering smoke GPS-denied для vision_bridge 0.3.1",
        [{"run_number": 1, "configuration_id": smoke_id, "profile": smoke_path,
          "mode": "loop_and_map_reuse", "target_altitude_m": 150, "seed": 6599}],
        continue_on_fail=False,
    )

    reuse_runs = []
    for number, seed in enumerate((6601, 6602, 6603), start=1):
        configuration_id = f"vb031-gps-denied-map-reuse-only-150m-s{seed}"
        profile = write_profile(
            "gps-denied-map_reuse_only-150m-s6501.json", configuration_id, seed
        )
        reuse_runs.append({
            "run_number": number,
            "configuration_id": configuration_id,
            "profile": profile,
            "mode": "map_reuse_only",
            "target_altitude_m": 150,
            "seed": seed,
        })
    suite(
        "vision-bridge-0.3.1-gps-denied-map-reuse-only-3",
        "Три GPS-denied польоти Map Reuse Only для vision_bridge 0.3.1",
        reuse_runs,
        continue_on_fail=True,
    )

    combined_id = "vb031-gps-denied-loop-and-map-reuse-150m-s6604"
    combined_path = write_profile(
        "gps-denied-smoke-loop_and_map_reuse-s6499.json", combined_id, 6604
    )
    suite(
        "vision-bridge-0.3.1-gps-denied-combined",
        "Контрольний GPS-denied Loop Closure + Map Reuse для vision_bridge 0.3.1",
        [{"run_number": 1, "configuration_id": combined_id, "profile": combined_path,
          "mode": "loop_and_map_reuse", "target_altitude_m": 150, "seed": 6604}],
        continue_on_fail=False,
    )


if __name__ == "__main__":
    main()
