"""Генерує окрему 15-польотну GPS-denied підкампанію на висоті 150 м."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "configurations" / "gps-denied"
VERSION = "1.1.0"
ISSUE = "https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/2"
COORDINATION_ISSUE = "https://github.com/Drone-Age/ENV_DEV_NEO_SIM1/issues/13"
FROZEN_MAP = "square-2km-qualification-map-150m"
ARDUPILOT = {
    "product": "ArduCopter", "version": "4.7.0",
    "source_commit": "1511f27194f1dcc3728270883047bdf022b3fd53",
}
MODES = ("disabled", "loop", "map_build", "map_reuse_only", "loop_and_map_reuse")
SEEDS = (6501, 6502, 6503)


def pose_graph(mode: str, seed: int) -> dict:
    allowed = {
        "disabled": [],
        "loop": ["current_session"],
        "map_build": ["current_session"],
        "map_reuse_only": ["loaded_map"],
        "loop_and_map_reuse": ["loaded_map", "current_session"],
    }[mode]
    map_artifact = ""
    if mode == "map_build":
        map_artifact = f"square-2km-gps-denied-map-150m-s{seed}"
    elif mode in {"map_reuse_only", "loop_and_map_reuse"}:
        map_artifact = FROZEN_MAP
    return {
        "mode": mode,
        "map_artifact": map_artifact,
        "allowed_match_sources": allowed,
        "source_altitude_m": 150.0 if map_artifact else None,
        "target_altitude_m": 150.0,
        "false_match_truth_distance_m": 20.0,
        "candidate_exclusion_keyframes": 400 if mode in {"loop", "map_build", "loop_and_map_reuse"} else 50,
        "candidate_selection": "best_score" if mode in {"loop", "map_build", "loop_and_map_reuse"} else "oldest",
        "min_fundamental_inlier_ratio": 0.30,
        "loaded_map_match_deadline_progress_m": 100.0,
        "current_session_match_start_progress_m": 1000.0,
        "current_session_match_deadline_progress_m": 1100.0,
    }


def profile_from(base: dict, mode: str, seed: int, *, smoke: bool = False) -> dict:
    profile = deepcopy(base)
    profile.pop("engineering_smoke_expectations", None)
    identifier = (
        f"gps-denied-smoke-{mode}-s{seed}"
        if smoke else f"gps-denied-{mode}-150m-s{seed}"
    )
    profile.update({
        "test_version": VERSION,
        "configuration_id": identifier,
        "description": f"GPS-denied підкампанія, режим {mode}, висота 150 м, seed {seed}",
        "vins_configuration_file": "../../vins-configurations/vins-neo-imx477-nominal.json",
        "governance": {"issue": ISSUE, "coordination_issue": COORDINATION_ISSUE},
    })
    profile["execution"]["gps_denied"] = True
    profile["navigation"] = {
        "flight_source_set": 2,
        "ekf_switch_allowed": True,
        "control_source": "VINS_ExternalNav",
        "vins_role": "flight_control_external_nav",
        "minimum_gps_status": 0,
        "gnss_fusion_during_route_allowed": False,
        "source_set_fallback_after_route_start_allowed": False,
        "source_set_confirmation_timeout_s": 30.0,
        "source_set_2_contract": {
            "position_xy": "ExternalNav",
            "velocity_xy": "ExternalNav",
            "position_z": "Barometer",
            "velocity_z": "None",
            "yaw": "ExternalNav",
        },
    }
    profile["pose_graph"] = pose_graph(mode, seed)
    profile["route"].update({
        "mission_file": "../../mission/square-250m-2km-150m.waypoints",
        "route_file": "../../mission/square-250m-2km-150m-route.json",
        "altitude_m": 150,
        "required_truth_distance_m": 2000,
        "required_reference_distance_m": 2000,
    })
    profile["bootstrap"]["alignment_altitude_m"] = 150.0
    profile["wind"]["seed"] = seed
    return profile


def write_profile(profile: dict) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{profile['configuration_id']}.json"
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"../configurations/gps-denied/{path.name}"


def main() -> None:
    base = json.loads(
        (ROOT / "configurations" / "pose-graph-campaign" / "pg-loop_closure-disabled-150m-s5101.json").read_text(encoding="utf-8")
    )
    runs = []
    for mode in MODES:
        for seed in SEEDS:
            profile = profile_from(base, mode, seed)
            runs.append({
                "run_number": len(runs) + 1,
                "configuration_id": profile["configuration_id"],
                "profile": write_profile(profile),
                "mode": mode,
                "target_altitude_m": 150,
                "seed": seed,
            })
    suite = {
        "schema": 1,
        "suite_id": "vins-square-250-2k-gps-denied-15",
        "display_name": "GPS-denied кваліфікація VINS Pose Graph на квадраті 250 м / 2 км",
        "official_flight_count": 15,
        "continue_on_fail": True,
        "retry_policy": "startup_retry_before_arm_only",
        "navigation_mode": "gps_denied",
        "issue": ISSUE,
        "coordination_issue": COORDINATION_ISSUE,
        "runtime_requirements": {"ardupilot": ARDUPILOT},
        "consolidator": "consolidate_gps_denied_campaign.py",
        "runs": runs,
    }
    (ROOT / "suites" / "vins-square-250-2k-gps-denied-15.json").write_text(
        json.dumps(suite, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    smoke = profile_from(base, "loop_and_map_reuse", 6499, smoke=True)
    (ROOT / "suites" / "vins-square-250-2k-gps-denied-smoke.json").write_text(
        json.dumps({
            "schema": 1,
            "suite_id": "vins-square-250-2k-gps-denied-smoke",
            "display_name": "Інженерний GPS-denied smoke",
            "continue_on_fail": False,
            "navigation_mode": "gps_denied",
            "issue": ISSUE,
            "runtime_requirements": {"ardupilot": ARDUPILOT},
            "consolidator": "consolidate_gps_denied_campaign.py",
            "runs": [{
                "run_number": 1,
                "configuration_id": smoke["configuration_id"],
                "profile": write_profile(smoke),
                "mode": "loop_and_map_reuse",
                "target_altitude_m": 150,
                "seed": 6499,
            }],
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
