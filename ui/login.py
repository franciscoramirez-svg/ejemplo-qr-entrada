from __future__ import annotations

import streamlit as st

from core.config import APP_NAME, APP_TAGLINE, COMPANY_NAME
from services.empleados import authenticate_admin, authenticate_employee


def _hero() -> None:
    st.markdown(
        f"""
        <section class="hero-card">
            <div class="logo-orbit">
                <div class="logo-core">N</div>
            </div>
            <p class="hero-company">{COMPANY_NAME}</p>
            <h1>{APP_NAME}</h1>
            <p class="hero-copy">{APP_TAGLINE}</p>
            <div class="hero-badges">
                <span>Face ID</span>
                <span>GPS</span>
                <span>Geocerca</span>
                <span>Dashboard</span>
                <span>Excel</span>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_welcome_flow() -> None:
    _hero()

    col_start, col_info = st.columns([1, 1])

    with col_start:
        if st.button("EMPEZAR", use_container_width=True, type="primary"):
            st.session_state["selected_profile"] = "chooser"

    with col_info:
        st.markdown(
            """
            <div class="glass-panel">
                <h3>Servicios integrados</h3>
                <p>Check-in inteligente, retardos, justificaciones, multi-sucursal y tablero administrativo.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if st.session_state["selected_profile"] != "chooser":
        return

    st.markdown("### Selecciona un acceso")
    mode_cols = st.columns(3)

    with mode_cols[0]:
        if st.button("Empleado", use_container_width=True):
            st.session_state["selected_profile"] = "employee"
    with mode_cols[1]:
        if st.button("Admin", use_container_width=True):
            st.session_state["selected_profile"] = "admin"
    with mode_cols[2]:
        if st.button("Kiosco", use_container_width=True):
            st.session_state["current_view"] = "kiosk"
            st.rerun()

    if st.session_state["selected_profile"] == "employee":
        _employee_login()
    elif st.session_state["selected_profile"] == "admin":
        _admin_login()


def _employee_login() -> None:
    with st.form("employee_login_form"):
        st.markdown("#### Acceso de empleado")
        employee_options = {
            f"{employee['name']} - {employee['role']}": employee["id"]
            for employee in st.session_state["employees"]
        }
        selected_employee_label = st.selectbox(
            "Empleado",
            options=list(employee_options.keys()),
        )
        pin = st.text_input("PIN", type="password", max_chars=4)
        submitted = st.form_submit_button("Ingresar")

    if submitted:
        employee_id = employee_options[selected_employee_label]
        employee = authenticate_employee(employee_id, pin)
        if employee:
            st.session_state["active_employee"] = employee
            st.session_state["current_view"] = "employee"
            st.rerun()
        st.error("PIN inválido.")


def _admin_login() -> None:
    with st.form("admin_login_form"):
        st.markdown("#### Acceso administrativo")
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        submitted = st.form_submit_button("Ingresar")

    if submitted:
        admin = authenticate_admin(username, password)
        if admin:
            st.session_state["current_view"] = "admin"
            st.rerun()
        st.error("Credenciales inválidas.")
