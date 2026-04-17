from __future__ import annotations


def simulate_face_match(employee_name: str) -> dict:
    return {
        "matched": True,
        "confidence": 0.97,
        "employee_name": employee_name,
        "liveness_ok": True,
    }
