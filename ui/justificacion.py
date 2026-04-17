from __future__ import annotations

from datetime import datetime

import streamlit as st

from core.rules import calculate_delay_status
from services.registros import create_record


def render_justification_form(
    employee: dict,
    branch: dict,
    lat: float,
    lon: float,
    channel: str,
) -> None:
    delay = calculate_delay_status(datetime.now())
    if not delay["requires_justification"]:
        return

    st.markdown(
        """
        <div class="glass-panel">
            <h3>Justificación sugerida</h3>
            <p>La hora actual cae en un escenario de retardo. Si deseas registrar entrada con justificación, úsalo aquí.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("justification_form"):
        justification = st.text_area(
            "Motivo",
            placeholder="Ej. Tráfico, incidente de transporte, visita externa autorizada...",
        )
        submitted = st.form_submit_button("Guardar entrada con justificación")

    if submitted:
        success, message = create_record(
            employee=employee,
            branch=branch,
            movement_type="entrada",
            employee_lat=lat,
            employee_lon=lon,
            channel=channel,
            justification=justification,
        )
        if success:
            st.success(message)
            st.rerun()
        st.error(message)
