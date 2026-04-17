from __future__ import annotations

import streamlit as st

from core.config import ADMINS
from core.security import verify_pin


def get_employee_by_id(employee_id: str) -> dict | None:
    return next(
        (employee for employee in st.session_state["employees"] if employee["id"] == employee_id),
        None,
    )


def authenticate_employee(employee_id: str, pin: str) -> dict | None:
    employee = get_employee_by_id(employee_id)
    if not employee:
        return None
    if verify_pin(pin, employee["pin_hash"]):
        return employee
    return None


def authenticate_admin(username: str, password: str) -> dict | None:
    return next(
        (
            admin
            for admin in ADMINS
            if admin["user"] == username and admin["password"] == password
        ),
        None,
    )
