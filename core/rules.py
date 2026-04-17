from __future__ import annotations

from datetime import datetime

from core.config import CRITICAL_LATE_MINUTES, LATE_TOLERANCE_MINUTES, SHIFT_START


def calculate_delay_status(check_time: datetime) -> dict:
    shift_start_minutes = SHIFT_START.hour * 60 + SHIFT_START.minute
    current_minutes = check_time.hour * 60 + check_time.minute
    delay_minutes = max(0, current_minutes - shift_start_minutes)

    if delay_minutes == 0:
        return {"minutes": 0, "level": "ON_TIME", "requires_justification": False}
    if delay_minutes <= LATE_TOLERANCE_MINUTES:
        return {"minutes": delay_minutes, "level": "TOLERANCE", "requires_justification": False}
    if delay_minutes <= CRITICAL_LATE_MINUTES:
        return {"minutes": delay_minutes, "level": "RETARDO", "requires_justification": True}
    return {"minutes": delay_minutes, "level": "CRITICO", "requires_justification": True}


def validate_flow(existing_records: list[dict], employee_id: str, movement_type: str) -> dict:
    employee_records = [row for row in existing_records if row["employee_id"] == employee_id]
    employee_records.sort(key=lambda row: row["timestamp"])

    if not employee_records:
        if movement_type == "salida":
            return {
                "allowed": False,
                "message": "No puedes registrar salida antes de una entrada.",
            }
        return {"allowed": True, "message": "Entrada inicial permitida."}

    last_record = employee_records[-1]
    if last_record["movement_type"] == movement_type:
        return {
            "allowed": False,
            "message": f"Movimiento duplicado detectado: ya existe una {movement_type} previa.",
        }

    return {"allowed": True, "message": "Flujo correcto."}
