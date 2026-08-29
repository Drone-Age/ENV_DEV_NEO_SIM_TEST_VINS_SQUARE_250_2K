"""Генерує квадратні QGC WPL місії для SIM та реального ArduCopter."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_CENTER_LAT = 50.31821195033009
DEFAULT_CENTER_LON = 31.137054110768155
EARTH_RADIUS_M = 6378137.0
SIDE_M = 250.0
LAPS = 2


def rotate(x_m: float, y_m: float, heading_deg: float) -> tuple[float, float]:
    angle = math.radians(heading_deg)
    return (
        x_m * math.cos(angle) - y_m * math.sin(angle),
        x_m * math.sin(angle) + y_m * math.cos(angle),
    )


def geodetic(x_m: float, y_m: float, center_lat: float, center_lon: float) -> tuple[float, float]:
    latitude = center_lat + math.degrees(y_m / EARTH_RADIUS_M)
    longitude = center_lon + math.degrees(
        x_m / (EARTH_RADIUS_M * math.cos(math.radians(center_lat)))
    )
    return latitude, longitude


def path_distance(points: list[dict[str, float]]) -> float:
    return sum(
        math.hypot(b["x_m"] - a["x_m"], b["y_m"] - a["y_m"])
        for a, b in zip(points, points[1:])
    )


def square_points(altitude_m: float, heading_deg: float) -> list[dict[str, float]]:
    half = SIDE_M / 2.0
    corners = [(-half, -half), (half, -half), (half, half), (-half, half)]
    rotated = [rotate(x_m, y_m, heading_deg) for x_m, y_m in corners]
    route = rotated + [rotated[0]] + rotated[1:] + [rotated[0]]
    return [
        {
            "x_m": round(x_m, 9),
            "y_m": round(y_m, 9),
            "altitude_m": float(altitude_m),
            "speed_mps": 7.0,
            "lap": min(index // 4 + 1, LAPS),
            "corner": index % 4,
            "route_progress_m": float(index * SIDE_M),
        }
        for index, (x_m, y_m) in enumerate(route)
    ]


def mission_preamble(add, altitude_m: float, center_lat: float, center_lon: float) -> None:
    """Зберігає штатний preset admission поза заліковою route distance."""
    add(1, 0, 16, lat=center_lat, lon=center_lon, alt=0)
    lat, lon = geodetic(10.0, 0.0, center_lat, center_lon)
    add(0, 3, 22, lat=lat, lon=lon, alt=10)
    add(0, 3, 19, p1=5, p3=1, lat=lat, lon=lon, alt=10)
    add(0, 3, 82, lat=center_lat, lon=center_lon, alt=20)
    add(0, 3, 19, p1=5, p3=1, lat=center_lat, lon=center_lon, alt=20)
    add(0, 3, 82, lat=lat, lon=lon, alt=10)
    add(0, 3, 19, p1=15, p3=1, lat=lat, lon=lon, alt=10)
    add(0, 0, 178, p1=1, p2=5, p3=-1)
    add(0, 3, 82, lat=center_lat, lon=center_lon, alt=altitude_m)


def write_mission(path: Path, build_rows) -> int:
    rows = []

    def add(current, frame, command, p1=0, p2=0, p3=0, p4=0, lat=0, lon=0, alt=0):
        sequence = len(rows)
        rows.append((sequence, current, frame, command, p1, p2, p3, p4, lat, lon, alt, 1))
        return sequence

    route_start_sequence = build_rows(add)
    lines = ["QGC WPL 110"] + ["\t".join(str(value) for value in row) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    return route_start_sequence


def generate_square(
    altitude_m: float,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    heading_deg: float = 0.0,
    output_dir: Path | None = None,
    site_id: str = "simulation-default",
) -> tuple[Path, Path, Path]:
    output = output_dir or ROOT / "mission"
    altitude_id = int(altitude_m)
    points = square_points(altitude_m, heading_deg)
    first = points[0]

    def rows(add):
        mission_preamble(add, altitude_m, center_lat, center_lon)
        # Підліт і стабілізація на першій вершині не входять у два залікові круги.
        lat, lon = geodetic(first["x_m"], first["y_m"], center_lat, center_lon)
        add(0, 0, 178, p1=1, p2=7, p3=-1)
        add(0, 3, 16, lat=lat, lon=lon, alt=altitude_id)
        add(0, 3, 19, p1=3, p3=1, lat=lat, lon=lon, alt=altitude_id)
        route_start = None
        for point in points:
            lat, lon = geodetic(point["x_m"], point["y_m"], center_lat, center_lon)
            sequence = add(0, 3, 16, lat=lat, lon=lon, alt=altitude_id)
            if route_start is None:
                route_start = sequence
        add(0, 0, 20)
        return route_start

    mission = output / f"square-250m-2km-{altitude_id}m.waypoints"
    route_start = write_mission(mission, rows)
    contract = output / f"square-250m-2km-{altitude_id}m-route.json"
    route_payload = {
        "schema": 2,
        "route_id": f"square-250m-2km-{altitude_id}m",
        "display_name": f"Квадрат 250×250 м, два круги, висота {altitude_id} м",
        "shape": "square",
        "side_m": SIDE_M,
        "laps": LAPS,
        "samples_per_lap": 4,
        "lap_distance_m": SIDE_M * 4,
        "route_distance_m": path_distance(points),
        "required_reference_distance_m": 2000.0,
        "route_start_sequence": route_start,
        "approach_excluded": True,
        "center": {"latitude_deg": center_lat, "longitude_deg": center_lon},
        "heading_deg": heading_deg,
        "maximum_corner_radius_from_center_m": math.hypot(SIDE_M / 2, SIDE_M / 2),
        "site_id": site_id,
        "mission_sha256": hashlib.sha256(mission.read_bytes()).hexdigest(),
        "points": points,
    }
    contract.write_text(json.dumps(route_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = output / f"square-250m-2km-{altitude_id}m-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "issue": "https://github.com/Drone-Age/ENV_DEV_NEO_SIM_TEST_VINS_SQUARE_250_2K/issues/1",
                "site_id": site_id,
                "files": {
                    mission.name: hashlib.sha256(mission.read_bytes()).hexdigest(),
                    contract.name: hashlib.sha256(contract.read_bytes()).hexdigest(),
                },
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    return mission, contract, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--center-lat", type=float, default=DEFAULT_CENTER_LAT)
    parser.add_argument("--center-lon", type=float, default=DEFAULT_CENTER_LON)
    parser.add_argument("--heading-deg", type=float, default=0.0)
    parser.add_argument("--site-id", default="simulation-default")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "mission")
    args = parser.parse_args()
    for altitude in (150.0, 40.0):
        for path in generate_square(
            altitude,
            center_lat=args.center_lat,
            center_lon=args.center_lon,
            heading_deg=args.heading_deg,
            output_dir=args.output_dir,
            site_id=args.site_id,
        ):
            print(path)


if __name__ == "__main__":
    main()
