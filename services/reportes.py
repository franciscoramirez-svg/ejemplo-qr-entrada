from __future__ import annotations

import pandas as pd

from services.registros import records_dataframe


def kpi_snapshot() -> dict:
    frame = records_dataframe()
    if frame.empty:
        return {
            "asistencia_hoy": 0,
            "retardos": 0,
            "criticos": 0,
            "sucursales_activas": 0,
        }

    today = pd.Timestamp.now().strftime("%Y-%m-%d")
    today_frame = frame[frame["fecha"] == today]

    return {
        "asistencia_hoy": int((today_frame["movement_type"] == "entrada").sum()),
        "retardos": int(today_frame["status"].isin(["RETARDO", "CRITICO"]).sum()),
        "criticos": int((today_frame["status"] == "CRITICO").sum()),
        "sucursales_activas": int(today_frame["branch_id"].nunique()),
    }
