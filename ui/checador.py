from __future__ import annotations

import streamlit as st

from services.biometria import simulate_face_match
from services.registros import create_record
from ui.justificacion import render_justification_form
from utils.time_utils import format_datetime


def render_employee_experience() -> None:
    employee = st.session_state["active_employee"]
    if not employee:
        st.session_state["current_view"] = "welcome"
        st.rerun()

    branch = next(
        branch for branch in st.session_state["branches"] if branch["id"] == employee["branch_id"]
    )

    st.markdown(
        f"""
        <div class="section-header">
            <div>
                <p class="eyebrow">Panel del empleado</p>
                <h2>{employee["name"]}</h2>
                <p>{employee["role"]} · {branch["name"]}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_a, col_b, col_c = st.columns([1.2, 1, 1])
    with col_a:
        st.markdown('<div class="glass-panel">', unsafe_allow_html=True)
        st.markdown("#### Identidad biométrica")
        face = simulate_face_match(employee["name"])
        st.metric("Coincidencia facial", f"{face['confidence'] * 100:.0f}%")
        st.caption("Liveness activo y match simulado para el MVP.")
        st.markdown("</div>", unsafe_allow_html=True)

    with col_b:
        st.markdown('<div class="glass-panel">', unsafe_allow_html=True)
        st.markdown("#### Ubicación")
        lat = st.number_input("Latitud", value=float(branch["lat"]), format="%.6f")
        lon = st.number_input("Longitud", value=float(branch["lon"]), format="%.6f")
        st.caption("En producción esto vendría del GPS del navegador o del kiosco.")
        st.markdown("</div>", unsafe_allow_html=True)

    with col_c:
        st.markdown('<div class="glass-panel">', unsafe_allow_html=True)
        st.markdown("#### Accesos")
        channel = st.selectbox("Método", ["rostro", "pin", "qr"])
        st.caption(f"Hora actual: {format_datetime()}")
        if st.button("Cerrar sesión", use_container_width=True):
            st.session_state["active_employee"] = None
            st.session_state["current_view"] = "welcome"
            st.session_state["selected_profile"] = None
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("### Registro de movimiento")
    action_cols = st.columns(2)

    with action_cols[0]:
        if st.button("Registrar ENTRADA", use_container_width=True, type="primary"):
            success, message = create_record(
                employee=employee,
                branch=branch,
                movement_type="entrada",
                employee_lat=lat,
                employee_lon=lon,
                channel=channel,
            )
            if success:
                st.success(message)
                st.rerun()
            st.error(message)

    with action_cols[1]:
        if st.button("Registrar SALIDA", use_container_width=True):
            success, message = create_record(
                employee=employee,
                branch=branch,
                movement_type="salida",
                employee_lat=lat,
                employee_lon=lon,
                channel=channel,
            )
            if success:
                st.success(message)
                st.rerun()
            st.error(message)

    render_justification_form(employee, branch, lat, lon, channel)
