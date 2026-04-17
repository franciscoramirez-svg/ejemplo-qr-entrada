from __future__ import annotations

import streamlit as st

from core.session import init_session_state
from ui.checador import render_employee_experience
from ui.dashboard import render_admin_dashboard
from ui.kiosco import render_kiosk_mode
from ui.login import render_welcome_flow
from utils.helpers import inject_global_styles


st.set_page_config(
    page_title="NeoAccess Pro",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

init_session_state()
inject_global_styles()


def main() -> None:
    current_view = st.session_state["current_view"]

    if current_view == "welcome":
        render_welcome_flow()
    elif current_view == "employee":
        render_employee_experience()
    elif current_view == "admin":
        render_admin_dashboard()
    elif current_view == "kiosk":
        render_kiosk_mode()


if __name__ == "__main__":
    main()
