"""Генерує 42-польотну кампанію Pose Graph на квадраті 250 м / 2 км."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "configurations" / "pose-graph-campaign"
TEST_ID = "VINS-POSE-GRAPH-SQUARE-250-2K-QUALIFICATION"
TEST_VERSION = "1.0.8"
TEST_REPOSITORY = "Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K"
ARDUPILOT_REQUIREMENT = {
    "product": "ArduCopter",
    "version": "4.7.0",
    "source_commit": "1511f27194f1dcc3728270883047bdf022b3fd53",
}
OFFICIAL_MAP_PREFIX = "square-2km-qualification-map"


def run_id(stage, mode, target, seed, source=None):
    mapping = f"-{source}to{target}" if source is not None else f"-{target}m"
    return f"pg-{stage}-{mode}{mapping}-s{seed}"


def main():
    base = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
    base["test_id"] = TEST_ID
    base["test_version"] = TEST_VERSION
    base["test_repository"] = TEST_REPOSITORY
    base["schema"] = 2
    base["runtime_requirements"] = {"ardupilot": deepcopy(ARDUPILOT_REQUIREMENT)}
    base["execution_backend"] = "simulation"
    base["backend_contracts"] = {
        "simulation": {
            "reference_source": "sim_truth",
            "reference_is_measurement_input": False,
            "launch_gazebo": True,
        },
        "real_vehicle": {
            "reference_source": "rtk_ppk_gnss",
            "reference_is_measurement_input": False,
            "launch_gazebo": False,
            "requires_site_profile": True,
            "requires_time_sync": True,
            "requires_geofence": True,
            "requires_reference_metadata": True,
            "arm_policy": "fail_closed",
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    runs = []

    def add(stage, mode, target, seed, source=None, pair=None, order=None):
        profile = deepcopy(base)
        # Engineering smoke gates belong only to the five smoke profiles
        # assembled below.  Inheriting the disabled identity gate into an
        # official loop/reuse run would classify a valid correction as a
        # disabled-mode failure.
        profile.pop("engineering_smoke_expectations", None)
        identifier = run_id(stage, mode, target, seed, source)
        profile["configuration_id"] = identifier
        profile["vins_configuration_file"] = "../../vins-configurations/vins-neo-imx477-nominal.json"
        profile["description"] = (
            f"Кампанія Pose Graph, етап {stage}, режим {mode}, "
            f"цільова висота {target} м"
        )
        profile["route"]["altitude_m"] = target
        profile["route"].update({
            "shape": "square",
            "side_m": 250,
            "loops": 2,
            "samples_per_loop": 4,
            "nominal_loop_distance_m": 1000,
            "route_total_distance_m": 2000,
            "required_truth_distance_m": 2000,
            "required_reference_distance_m": 2000,
            "lap_boundary_progress_m": 1000,
            "first_match_window_m": 100,
            "mission_timeout_s": 900,
        })
        profile["route"]["mission_file"] = f"../../mission/square-250m-2km-{target}m.waypoints"
        profile["route"]["route_file"] = f"../../mission/square-250m-2km-{target}m-route.json"
        profile["bootstrap"]["alignment_altitude_m"] = float(target)
        profile["bootstrap"]["route_start_sequence"] = 12
        profile["wind"]["seed"] = seed
        allowed = {
            "disabled": [],
            "loop": ["current_session"],
            "map_build": ["current_session"],
            "map_reuse_only": ["loaded_map"],
            "loop_and_map_reuse": ["loaded_map", "current_session"],
        }[mode]
        profile["pose_graph"] = {
            "mode": mode,
            "map_artifact": f"{OFFICIAL_MAP_PREFIX}-{source if source is not None else target}m" if mode in {
                "map_build", "map_reuse_only", "loop_and_map_reuse"
            } else "",
            "allowed_match_sources": allowed,
            "source_altitude_m": float(source if source is not None else target) if mode in {
                "map_build", "map_reuse_only", "loop_and_map_reuse"
            } else None,
            "target_altitude_m": float(target),
            "false_match_truth_distance_m": 20.0,
            "candidate_exclusion_keyframes": (
                400 if mode in {"loop", "map_build", "loop_and_map_reuse"} else 50
            ),
            "candidate_selection": (
                "best_score" if mode in {"loop", "map_build", "loop_and_map_reuse"} else "oldest"
            ),
            "loaded_map_match_deadline_progress_m": 100.0,
            "current_session_match_start_progress_m": 1000.0,
            "current_session_match_deadline_progress_m": 1100.0,
        }
        path = OUT / f"{identifier}.json"
        path.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        runs.append({
            "run_number": len(runs) + 1,
            "configuration_id": identifier,
            "profile": f"../configurations/pose-graph-campaign/{path.name}",
            "stage": stage,
            "mode": mode,
            "target_altitude_m": target,
            "source_altitude_m": source,
            "seed": seed,
            "pair_id": pair,
            "pair_order": order,
        })

    # Five counterbalanced OFF/loop pairs (10 flights).
    for index, seed in enumerate((5101, 5102, 5103, 5104, 5105), 1):
        modes = ("disabled", "loop") if index % 2 else ("loop", "disabled")
        for order, mode in enumerate(modes, 1):
            add("loop_closure", mode, 150, seed, pair=f"loop-{index}", order=order)
    add("map_build", "map_build", 150, 5201)
    add("map_build", "map_build", 40, 5202)
    # One shared OFF plus same/cross map query for each seed and target (18 flights).
    for target, seeds in ((150, (5301, 5302, 5303)), (40, (5401, 5402, 5403))):
        for seed in seeds:
            add("map_reuse_only", "disabled", target, seed, pair=f"reuse-{target}-{seed}")
            add("map_reuse_only", "map_reuse_only", target, seed, source=target, pair=f"reuse-{target}-{seed}")
            add("map_reuse_only", "map_reuse_only", target, seed, source=40 if target == 150 else 150, pair=f"reuse-{target}-{seed}")
    # Three fixed seeds for each direction, 12 flights.
    for source, target, seeds in (
        (150, 150, (5301, 5302, 5303)),
        (40, 150, (5301, 5302, 5303)),
        (40, 40, (5401, 5402, 5403)),
        (150, 40, (5401, 5402, 5403)),
    ):
        for seed in seeds:
            add("loop_and_map_reuse", "loop_and_map_reuse", target, seed, source=source)

    assert len(runs) == 42
    suite = {
        "schema": 2,
        "suite_id": "vins-mono-square-250-2k-pose-graph-42",
        "display_name": "Кваліфікація VINS‑Mono Pose Graph на квадраті 250 м / 2 км",
        "continue_on_fail": True,
        "official_flight_count": 42,
        "retry_policy": "startup_retry_before_arm_only",
        "execution_backend": "simulation",
        "reference": {
            "source": "sim_truth",
            "used_as_vins_input": False,
        },
        "route_contract": {
            "shape": "square",
            "side_m": 250,
            "laps": 2,
            "route_distance_m": 2000,
            "lap_boundary_progress_m": 1000,
        },
        "runtime_requirements": {"ardupilot": deepcopy(ARDUPILOT_REQUIREMENT)},
        "runs": runs,
    }
    (ROOT / "suites" / "vins-mono-square-250-2k-pose-graph-42.json").write_text(
        json.dumps(suite, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    smoke = []
    smoke_modes = (
        ("disabled", None),
        ("loop", None),
        ("map_build", 150),
        ("map_reuse_only", 150),
        ("loop_and_map_reuse", 150),
    )
    for order, (mode, source) in enumerate(smoke_modes, 1):
        template = deepcopy(base)
        identifier = f"pg-smoke-{order}-{mode}"
        template["configuration_id"] = identifier
        template["description"] = f"Інженерний smoke режиму {mode}"
        template["vins_configuration_file"] = "../../vins-configurations/vins-neo-imx477-nominal.json"
        template["route"].update({
            "shape": "square",
            "side_m": 250,
            "loops": 2,
            "samples_per_loop": 4,
            "nominal_loop_distance_m": 1000,
            "route_total_distance_m": 2000,
            "required_truth_distance_m": 2000,
            "required_reference_distance_m": 2000,
            "lap_boundary_progress_m": 1000,
            "first_match_window_m": 100,
            "mission_timeout_s": 900,
            "mission_file": "../../mission/square-250m-2km-150m.waypoints",
            "route_file": "../../mission/square-250m-2km-150m-route.json",
        })
        template["bootstrap"]["route_start_sequence"] = 12
        template["wind"]["seed"] = 4901
        allowed = {
            "disabled": [], "loop": ["current_session"], "map_build": ["current_session"],
            "map_reuse_only": ["loaded_map"],
            "loop_and_map_reuse": ["loaded_map", "current_session"],
        }[mode]
        template["pose_graph"] = {
            "mode": mode,
            "map_artifact": "square-2km-smoke-map-150m" if source is not None else "",
            "allowed_match_sources": allowed,
            "source_altitude_m": float(source) if source is not None else None,
            "target_altitude_m": 150.0,
            "false_match_truth_distance_m": 20.0,
            "candidate_exclusion_keyframes": (
                400 if mode in {"loop", "map_build", "loop_and_map_reuse"} else 50
            ),
            "candidate_selection": (
                "best_score" if mode in {"loop", "map_build", "loop_and_map_reuse"} else "oldest"
            ),
            "loaded_map_match_deadline_progress_m": 100.0,
            "current_session_match_start_progress_m": 1000.0,
            "current_session_match_deadline_progress_m": 1100.0,
        }
        template["engineering_smoke_expectations"] = {
            "require_match": mode != "disabled",
            "required_match_source": (
                "loaded_map" if mode in {"map_reuse_only", "loop_and_map_reuse"}
                else "current_session" if mode != "disabled" else None
            ),
            "require_corrected_change_after_match": mode != "disabled",
            "require_identity_when_disabled": mode == "disabled",
        }
        path = OUT / f"{identifier}.json"
        path.write_text(
            json.dumps(template, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        smoke.append({"configuration_id": identifier, "profile": f"../configurations/pose-graph-campaign/{path.name}"})
    (ROOT / "suites" / "vins-mono-square-250-2k-pose-graph-smoke.json").write_text(
        json.dumps({
            "schema": 1,
            "suite_id": "vins-mono-square-250-2k-pose-graph-smoke",
            "display_name": "Інженерний smoke VINS‑Mono Pose Graph на квадраті 2 км",
            "vins_configuration_id": "vins-neo-imx477-cs2006-nominal",
            "continue_on_fail": True,
            "execution_backend": "simulation",
            "reference": {
                "source": "sim_truth",
                "used_as_vins_input": False,
            },
            "runtime_requirements": {"ardupilot": deepcopy(ARDUPILOT_REQUIREMENT)},
            "configurations": smoke,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    default_profile = json.loads((OUT / "pg-smoke-1-disabled.json").read_text(encoding="utf-8"))
    default_profile["vins_configuration_file"] = "vins-configurations/vins-neo-imx477-nominal.json"
    default_profile["route"]["mission_file"] = "mission/square-250m-2km-150m.waypoints"
    default_profile["route"]["route_file"] = "mission/square-250m-2km-150m-route.json"
    (ROOT / "profile.json").write_text(
        json.dumps(default_profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
