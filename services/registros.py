from __future__ import annotations

from datetime import datetime
from io import BytesIO
from uuid import uuid4

import pandas as pd
import streamlit as st

from core.geo import is_within_geofence
from core.rules import calculate_delay_status, validate_flow


def list_records() -> list[dict]:
    return st.session_state["records"]


def create_record(
    employee: dict,
    branch: dict,
    movement_type: str,
    employee_lat: float,
    employee_lon: float,
    channel: str,
    justification: str = "",
) -> tuple[bool, str]:
    records = list_records()
    flow_check = validate_flow(records, employee["id"], movement_type)
    if not flow_check["allowed"]:
        return False, flow_check["message"]

    geo_ok, distance = is_within_geofence(
        employee_lat,
        employee_lon,
        branch["lat"],
        branch["lon"],
        branch["radius_meters"],
    )
    now = datetime.now()
    delay = calculate_delay_status(now) if movement_type == "entrada" else {
        "minutes": 0,
        "level": "SALIDA",
        "requires_justification": False,
    }

    record = {
        "id": f"reg-{uuid4().hex[:8]}",
        "employee_id": employee["id"],
        "employee_name": employee["name"],
        "branch_id": branch["id"],
        "branch_name": branch["name"],
        "movement_type": movement_type,
        "timestamp": now,
        "status": delay["level"],
        "delay_minutes": delay["minutes"],
        "geo_ok": geo_ok,
        "distance_meters": round(distance, 2),
        "justification": justification,
        "channel": channel,
    }
    st.session_state["records"].append(record)
    return True, "Registro guardado correctamente."


def records_dataframe() -> pd.DataFrame:
    rows = list_records()
    if not rows:
        return pd.DataFrame()

    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame["fecha"] = frame["timestamp"].dt.strftime("%Y-%m-%d")
    frame["hora"] = frame["timestamp"].dt.strftime("%H:%M")
    return frame.sort_values("timestamp", ascending=False)


def export_records_excel() -> bytes:
    output = BytesIO()
    frame = records_dataframe()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        frame.to_excel(writer, index=False, sheet_name="registros")

    return output.getvalue()
