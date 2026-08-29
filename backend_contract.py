"""Fail-closed контракти simulation і майбутнього real_vehicle запуску."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


MIN_ROUTE_RADIUS_M = math.hypot(125.0, 125.0)
ALLOWED_BACKENDS = {"simulation", "real_vehicle"}


class ContractError(ValueError):
    pass


def load_json(path: Path, label: str) -> dict:
    if not path.is_file():
        raise ContractError(f"{label} не знайдено: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} пошкоджено: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} повинен містити JSON object")
    return value


def validate_profile_backend(profile: dict, backend: str) -> dict:
    if backend not in ALLOWED_BACKENDS:
        raise ContractError(f"Непідтримуваний backend: {backend}")
    contracts = profile.get("backend_contracts") or {}
    contract = contracts.get(backend)
    if not isinstance(contract, dict):
        raise ContractError(f"У profile відсутній backend_contracts.{backend}")
    if contract.get("reference_is_measurement_input") is not False:
        raise ContractError("Reference data не може бути входом VINS або Pose Graph")
    if backend == "real_vehicle" and contract.get("launch_gazebo") is not False:
        raise ContractError("real_vehicle не може запускати Gazebo")
    return contract


def validate_reference(reference: dict, minimum_coverage: float) -> None:
    if reference.get("schema") != 1:
        raise ContractError("Непідтримувана schema RTK/PPK reference")
    if reference.get("source") not in {"rtk_gnss", "ppk_gnss"}:
        raise ContractError("Reference source має бути rtk_gnss або ppk_gnss")
    if reference.get("used_as_vins_input") is not False:
        raise ContractError("RTK/PPK заборонено використовувати як вхід VINS")
    if float(reference.get("coverage_fraction", 0.0)) < minimum_coverage:
        raise ContractError("Недостатня coverage RTK/PPK reference")
    if reference.get("minimum_solution_quality") != "fixed":
        raise ContractError("Acceptance reference повинен використовувати лише RTK fixed epochs")
    if not reference.get("time_base") or float(reference.get("maximum_time_offset_ms", 1e9)) > 20.0:
        raise ContractError("Не підтверджено часову синхронізацію reference ≤20 мс")


def validate_real_vehicle(
    profile_path: Path,
    site_path: Path,
    reference_path: Path | None,
) -> dict:
    profile = load_json(profile_path, "Profile")
    validate_profile_backend(profile, "real_vehicle")
    site = load_json(site_path, "Site profile")
    if site.get("schema") != 1 or site.get("approved") is not True:
        raise ContractError("Site profile не затверджено")
    for field in ("site_id", "center", "home", "heading_deg", "geofence", "rtl", "time_sync", "rtk", "camera_calibration_sha256"):
        if field not in site:
            raise ContractError(f"Site profile не містить обов'язкове поле {field}")
    center = site["center"]
    home = site["home"]
    for label, point in (("center", center), ("home", home)):
        if not isinstance(point, dict) or not all(key in point for key in ("latitude_deg", "longitude_deg")):
            raise ContractError(f"{label} має містити latitude_deg і longitude_deg")
    altitude = float((profile.get("route") or {}).get("altitude_m", -1))
    allowed_altitudes = [float(value) for value in site.get("allowed_altitudes_m", [])]
    if altitude not in allowed_altitudes:
        raise ContractError(f"Висота {altitude:g} м не дозволена site profile")
    if float(site["geofence"].get("radius_m", 0.0)) < MIN_ROUTE_RADIUS_M + 25.0:
        raise ContractError("Геозона не покриває квадрат і 25-метровий safety margin")
    if site["rtl"].get("enabled") is not True or float(site["rtl"].get("altitude_m", 0.0)) <= 0:
        raise ContractError("Не задано безпечний RTL")
    if site["time_sync"].get("required") is not True or float(site["time_sync"].get("maximum_offset_ms", 1e9)) > 20.0:
        raise ContractError("Site profile не гарантує часову синхронізацію ≤20 мс")
    if site["rtk"].get("minimum_solution_quality") != "fixed":
        raise ContractError("Site profile має вимагати RTK fixed")
    calibration_hash = str(site.get("camera_calibration_sha256", ""))
    if len(calibration_hash) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in calibration_hash):
        raise ContractError("Не задано валідний SHA-256 калібрування реальної камери")
    if reference_path is not None:
        validate_reference(load_json(reference_path, "RTK/PPK reference"), 0.999)
    elif site["rtk"].get("mode") == "ppk":
        raise ContractError("PPK mode потребує -ReferenceFile")
    return {
        "passed": True,
        "backend": "real_vehicle",
        "site_id": site["site_id"],
        "reference_mode": site["rtk"].get("mode"),
        "arm_policy": "fail_closed",
        "gazebo": False,
        "reference_is_measurement_input": False,
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--backend", choices=sorted(ALLOWED_BACKENDS), required=True)
    parser.add_argument("--site-profile", type=Path)
    parser.add_argument("--reference-file", type=Path)
    args = parser.parse_args()
    try:
        profile = load_json(args.profile, "Profile")
        result = {"passed": True, "backend": args.backend, "profile_sha256": sha256(args.profile)}
        result.update(validate_profile_backend(profile, args.backend))
        if args.backend == "real_vehicle":
            if args.site_profile is None:
                raise ContractError("real_vehicle потребує -SiteProfile")
            result.update(validate_real_vehicle(args.profile, args.site_profile, args.reference_file))
        elif args.site_profile or args.reference_file:
            raise ContractError("SiteProfile/ReferenceFile дозволені лише для real_vehicle")
    except ContractError as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
