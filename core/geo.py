from __future__ import annotations

from math import atan2, cos, radians, sin, sqrt


def haversine_distance_meters(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    radius_earth = 6371000
    phi_1 = radians(lat1)
    phi_2 = radians(lat2)
    delta_phi = radians(lat2 - lat1)
    delta_lambda = radians(lon2 - lon1)

    a = (
        sin(delta_phi / 2) ** 2
        + cos(phi_1) * cos(phi_2) * sin(delta_lambda / 2) ** 2
    )
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return radius_earth * c


def is_within_geofence(
    employee_lat: float,
    employee_lon: float,
    branch_lat: float,
    branch_lon: float,
    radius_meters: int,
) -> tuple[bool, float]:
    distance = haversine_distance_meters(
        employee_lat, employee_lon, branch_lat, branch_lon
    )
    return distance <= radius_meters, distance
