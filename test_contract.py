from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from backend_contract import ContractError, validate_profile_backend, validate_real_vehicle
from consolidate_pose_graph_campaign import build as build_campaign
from consolidate_pose_graph_smoke import build as build_smoke
from generate_mission import generate_square, path_distance, square_points
from runtime_contract import evaluate_ardupilot


ROOT = Path(__file__).resolve().parent
TEST_ID = "VINS-POSE-GRAPH-SQUARE-250-2K-QUALIFICATION"
REPOSITORY = "Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K"
ISSUE = "https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/1"
ARDUPILOT_COMMIT = "1511f27194f1dcc3728270883047bdf022b3fd53"


def load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def profiles() -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((ROOT / "configurations" / "pose-graph-campaign").glob("*.json"))
    ]


def valid_site() -> dict:
    return {
        "schema": 1,
        "site_id": "approved-test-site",
        "approved": True,
        "center": {"latitude_deg": 50.0, "longitude_deg": 30.0},
        "home": {"latitude_deg": 50.0, "longitude_deg": 30.0},
        "heading_deg": 0.0,
        "camera_calibration_sha256": "a" * 64,
        "allowed_altitudes_m": [40.0, 150.0],
        "geofence": {"radius_m": 225.0, "maximum_altitude_m": 170.0},
        "rtl": {"enabled": True, "altitude_m": 30.0},
        "time_sync": {"required": True, "maximum_offset_ms": 20.0},
        "rtk": {"mode": "ppk", "minimum_solution_quality": "fixed"},
    }


def valid_reference() -> dict:
    return {
        "schema": 1,
        "source": "ppk_gnss",
        "used_as_vins_input": False,
        "coverage_fraction": 0.999,
        "minimum_solution_quality": "fixed",
        "time_base": "GPS",
        "maximum_time_offset_ms": 20.0,
        "epochs_file": "reference.pos",
    }


def test_contract_identity_and_governance():
    contract = load("test-contract.json")
    assert contract["test_id"] == TEST_ID
    assert contract["repository"] == REPOSITORY
    assert contract["submodule_path"] == "tests/vins_square_250_2k"
    assert contract["backends"] == ["simulation", "real_vehicle"]
    assert contract["issue"] == ISSUE
    assert contract["coordination_issue"].endswith("/issues/12")
    assert (ROOT / "VERSION").read_text().strip() == "1.0.1"


@pytest.mark.parametrize("altitude", [150, 40])
def test_canonical_square_contract(altitude):
    route = load(f"mission/square-250m-2km-{altitude}m-route.json")
    mission = ROOT / f"mission/square-250m-2km-{altitude}m.waypoints"
    manifest = load(f"mission/square-250m-2km-{altitude}m-manifest.json")
    assert route["shape"] == "square"
    assert route["side_m"] == 250.0
    assert route["laps"] == 2
    assert route["lap_distance_m"] == 1000.0
    assert route["route_distance_m"] == 2000.0
    assert route["required_reference_distance_m"] == 2000.0
    assert route["distance_assurance_tail_m"] == 40.0
    assert route["mission_planned_distance_m"] == 2040.0
    assert route["distance_assurance_tail_excluded_from_lap_metrics"] is True
    assert route["approach_excluded"] is True
    assert route["route_start_sequence"] == 12
    assert len(route["points"]) == 9
    assert route["points"][0]["x_m"] == route["points"][4]["x_m"] == route["points"][8]["x_m"]
    assert route["points"][0]["y_m"] == route["points"][4]["y_m"] == route["points"][8]["y_m"]
    assert math.isclose(route["maximum_corner_radius_from_center_m"], math.hypot(125, 125))
    digest = hashlib.sha256(mission.read_bytes()).hexdigest()
    assert route["mission_sha256"] == digest
    assert manifest["files"][mission.name] == digest
    assert manifest["issue"] == ISSUE
    rows = mission.read_text(encoding="ascii").splitlines()
    assert len(rows) == 1 + 24


def test_square_rotation_preserves_exact_distance(tmp_path):
    points = square_points(150.0, 37.0)
    assert math.isclose(path_distance(points), 2000.0, abs_tol=1e-6)
    mission, route, manifest = generate_square(
        150.0, 50.0, 30.0, 37.0, tmp_path, "approved-test-site"
    )
    payload = json.loads(route.read_text(encoding="utf-8"))
    assert payload["site_id"] == "approved-test-site"
    assert payload["heading_deg"] == 37.0
    assert mission.is_file() and manifest.is_file()


def test_campaign_has_exact_42_fixed_runs():
    suite = load("suites/vins-mono-square-250-2k-pose-graph-42.json")
    assert suite["official_flight_count"] == 42
    assert [run["run_number"] for run in suite["runs"]] == list(range(1, 43))
    assert sum(run["stage"] == "loop_closure" for run in suite["runs"]) == 10
    assert sum(run["stage"] == "map_build" for run in suite["runs"]) == 2
    assert sum(run["stage"] == "map_reuse_only" for run in suite["runs"]) == 18
    assert sum(run["stage"] == "loop_and_map_reuse" for run in suite["runs"]) == 12
    assert suite["retry_policy"] == "startup_retry_before_arm_only"
    assert suite["runtime_requirements"]["ardupilot"]["version"] == "4.7.0"
    assert suite["runtime_requirements"]["ardupilot"]["source_commit"] == ARDUPILOT_COMMIT


def test_smoke_has_all_five_modes():
    suite = load("suites/vins-mono-square-250-2k-pose-graph-smoke.json")
    assert len(suite["configurations"]) == 5
    assert [item["configuration_id"].rsplit("-", 1)[-1] for item in suite["configurations"]] == [
        "disabled", "loop", "map_build", "map_reuse_only", "loop_and_map_reuse"
    ]


def test_all_47_profiles_are_square_backend_safe_and_bag_free():
    all_profiles = profiles()
    assert len(all_profiles) == 47
    for profile in all_profiles:
        assert profile["test_id"] == TEST_ID
        assert profile["test_repository"] == REPOSITORY
        assert profile["route"]["shape"] == "square"
        assert profile["route"]["side_m"] == 250
        assert profile["route"]["loops"] == 2
        assert profile["route"]["required_reference_distance_m"] == 2000
        assert profile["bootstrap"]["route_start_sequence"] == 12
        assert profile["navigation"]["vins_role"] == "measurement_only"
        assert profile["navigation"]["flight_source_set"] == 1
        assert profile["navigation"]["ekf_switch_allowed"] is False
        assert profile["runtime_requirements"]["ardupilot"]["source_commit"] == ARDUPILOT_COMMIT
        assert validate_profile_backend(profile, "simulation")["reference_source"] == "sim_truth"
        assert validate_profile_backend(profile, "real_vehicle")["launch_gazebo"] is False
        assert not any(token in json.dumps(profile).lower() for token in ("full_camera_imu_bag", '"rosbag"', '"mcap"'))


def test_match_windows_are_lap_aware():
    for profile in profiles():
        pose = profile["pose_graph"]
        assert pose["loaded_map_match_deadline_progress_m"] == 100.0
        assert pose["current_session_match_start_progress_m"] == 1000.0
        assert pose["current_session_match_deadline_progress_m"] == 1100.0


def test_map_artifacts_are_isolated_from_500m_campaign():
    names = {
        profile["pose_graph"]["map_artifact"]
        for profile in profiles()
        if profile["pose_graph"]["map_artifact"]
    }
    assert names == {
        "square-2km-smoke-map-150m",
        "square-2km-qualification-map-150m",
        "square-2km-qualification-map-40m",
    }


def test_real_vehicle_template_fails_closed():
    with pytest.raises(ContractError, match="не затверджено"):
        validate_real_vehicle(
            ROOT / "profile.json",
            ROOT / "site-profiles" / "real-vehicle-template.json",
            ROOT / "reference" / "ppk-reference-template.json",
        )


def test_real_vehicle_valid_site_and_ppk_contract(tmp_path):
    site = tmp_path / "site.json"
    reference = tmp_path / "reference.json"
    site.write_text(json.dumps(valid_site()), encoding="utf-8")
    reference.write_text(json.dumps(valid_reference()), encoding="utf-8")
    result = validate_real_vehicle(ROOT / "profile.json", site, reference)
    assert result["passed"] is True
    assert result["gazebo"] is False
    assert result["reference_is_measurement_input"] is False


def test_real_vehicle_rejects_nonfixed_or_low_coverage_ppk(tmp_path):
    site = tmp_path / "site.json"
    reference = tmp_path / "reference.json"
    site.write_text(json.dumps(valid_site()), encoding="utf-8")
    payload = valid_reference()
    payload["coverage_fraction"] = 0.9
    reference.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ContractError, match="coverage"):
        validate_real_vehicle(ROOT / "profile.json", site, reference)


def test_launcher_exposes_backends_and_keeps_rosbag_explicit():
    launcher = (ROOT / "run-test.ps1").read_text(encoding="utf-8")
    assert "[ValidateSet('simulation', 'real_vehicle')]" in launcher
    assert "[string]$SiteProfile" in launcher
    assert "[string]$ReferenceFile" in launcher
    assert "if ($Rosbag)" in launcher
    assert "profileConfig" not in launcher.split("if ($Rosbag)", 1)[0][-100:]
    assert "$args += '-Rosbag'" in launcher


def test_empty_evidence_reports_are_honest(tmp_path):
    campaign = build_campaign(
        ROOT / "suites" / "vins-mono-square-250-2k-pose-graph-42.json", tmp_path
    )
    smoke = build_smoke(
        ROOT / "suites" / "vins-mono-square-250-2k-pose-graph-smoke.json", tmp_path
    )
    assert campaign["summary"]["recorded"] == 0
    assert campaign["summary"]["not_run"] == 42
    assert len(campaign["results"]) == 42
    assert len(campaign["verdicts"]) == 7
    assert campaign["test_repository"] == REPOSITORY
    assert ISSUE in campaign["issues"]
    assert smoke["summary"]["recorded"] == 0
    assert smoke["summary"]["not_run"] == 5
    assert len(smoke["results"]) == 5


def test_runtime_contract_pins_ardupilot_binary_and_commit():
    report = {
        "module_versions": {
            "ArduCopter SITL": {
                "firmware_version": "4.7.0",
                "source_commit": ARDUPILOT_COMMIT,
                "binary_sha256": "abc",
                "actual_binary_sha256": "abc",
            }
        }
    }
    requirement = {"version": "4.7.0", "source_commit": ARDUPILOT_COMMIT}
    assert evaluate_ardupilot(report, requirement)["passed"] is True
    report["module_versions"]["ArduCopter SITL"]["actual_binary_sha256"] = "bad"
    assert evaluate_ardupilot(report, requirement)["passed"] is False


def test_no_tracked_bag_artifacts():
    forbidden = {".bag", ".db3", ".mcap"}
    assert not [path for path in ROOT.rglob("*") if path.is_file() and path.suffix.lower() in forbidden]
