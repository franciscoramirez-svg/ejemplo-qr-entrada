from __future__ import annotations

from datetime import time


APP_NAME = "NeoAccess Pro"
APP_TAGLINE = "Control inteligente de asistencia, acceso y operación multi-sucursal"
COMPANY_NAME = "Nova Orbit Systems"

DEFAULT_BRANCH = {
    "id": "suc-001",
    "name": "Corporativo Centro",
    "lat": 19.432608,
    "lon": -99.133209,
    "radius_meters": 150,
}

SHIFT_START = time(hour=9, minute=0)
LATE_TOLERANCE_MINUTES = 10
CRITICAL_LATE_MINUTES = 30

BRANCHES = [
    DEFAULT_BRANCH,
    {
        "id": "suc-002",
        "name": "Sucursal Norte",
        "lat": 25.686614,
        "lon": -100.316113,
        "radius_meters": 180,
    },
    {
        "id": "suc-003",
        "name": "Sucursal Bajio",
        "lat": 20.588793,
        "lon": -100.389889,
        "radius_meters": 180,
    },
]

EMPLOYEES = [
    {
        "id": "emp-001",
        "name": "Andrea Ruiz",
        "role": "Operaciones",
        "pin": "1234",
        "branch_id": "suc-001",
    },
    {
        "id": "emp-002",
        "name": "Luis Mendez",
        "role": "Ventas",
        "pin": "5678",
        "branch_id": "suc-002",
    },
    {
        "id": "emp-003",
        "name": "Sofia Navarro",
        "role": "RH",
        "pin": "2468",
        "branch_id": "suc-003",
    },
]

ADMINS = [
    {"user": "admin", "password": "admin123", "name": "Dirección General"},
]
