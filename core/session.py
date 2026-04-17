from __future__ import annotations

from datetime import datetime, timedelta

import streamlit as st

from core.config import BRANCHES, EMPLOYEES
from core.security import hash_pin


def _seed_records() -> list[dict]:
    now = datetime.now()
    return [
        {
            "id": "reg-001",
            "employee_id": "emp-001",
            "employee_name": "Andrea Ruiz",
            "branch_id": "suc-001",
            "branch_name": "Corporativo Centro",
            "movement_type": "entrada",
            "timestamp": now.replace(hour=8, minute=57, second=0, microsecond=0),
            "status": "ON_TIME",
            "delay_minutes": 0,
            "geo_ok": True,
            "distance_meters": 18,
            "justification": "",
            "channel": "rostro",
        },
        {
            "id": "reg-002",
            "employee_id": "emp-002",
            "employee_name": "Luis Mendez",
            "branch_id": "suc-002",
            "branch_name": "Sucursal Norte",
            "movement_type": "entrada",
            "timestamp": now.replace(hour=9, minute=22, second=0, microsecond=0),
            "status": "RETARDO",
            "delay_minutes": 22,
            "geo_ok": True,
            "distance_meters": 31,
            "justification": "Tráfico por cierre vial.",
            "channel": "pin",
        },
        {
            "id": "reg-003",
            "employee_id": "emp-003",
            "employee_name": "Sofia Navarro",
            "branch_id": "suc-003",
            "branch_name": "Sucursal Bajio",
            "movement_type": "entrada",
            "timestamp": now - timedelta(hours=1, minutes=10),
            "status": "ON_TIME",
            "delay_minutes": 0,
            "geo_ok": False,
            "distance_meters": 215,
            "justification": "Home office autorizado.",
            "channel": "qr",
        },
    ]


def init_session_state() -> None:
    if "current_view" not in st.session_state:
        st.session_state["current_view"] = "welcome"
    if "selected_profile" not in st.session_state:
        st.session_state["selected_profile"] = None
    if "active_employee" not in st.session_state:
        st.session_state["active_employee"] = None
    if "records" not in st.session_state:
        st.session_state["records"] = _seed_records()
    if "employees" not in st.session_state:
        st.session_state["employees"] = [
            {**employee, "pin_hash": hash_pin(employee["pin"])} for employee in EMPLOYEES
        ]
    if "branches" not in st.session_state:
        st.session_state["branches"] = BRANCHES
    if "pending_justification" not in st.session_state:
        st.session_state["pending_justification"] = None
