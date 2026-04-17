from __future__ import annotations

import pandas as pd
import streamlit as st

from services.reportes import kpi_snapshot
from services.registros import export_records_excel, records_dataframe
from services.supabase_client import get_supabase_settings


def render_admin_dashboard() -> None:
    snapshot = kpi_snapshot()
    records = records_dataframe()
    supabase = get_supabase_settings()

    st.markdown(
        """
        <div class="section-header">
            <div>
                <p class="eyebrow">Dashboard administrativo</p>
                <h2>Visibilidad operativa en tiempo real</h2>
                <p>KPIs, registros, sucursales y exportación centralizada.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    metric_cols = st.columns(4)
    metric_cols[0].metric("Asistencia hoy", snapshot["asistencia_hoy"])
    metric_cols[1].metric("Retardos", snapshot["retardos"])
    metric_cols[2].metric("Críticos", snapshot["criticos"])
    metric_cols[3].metric("Sucursales activas", snapshot["sucursales_activas"])

    st.markdown("### Estado del backend")
    if supabase["configured"]:
        st.success("Supabase configurado. El proyecto está listo para conectarse a datos reales.")
    else:
        st.warning("Supabase aún no está configurado. El MVP está trabajando con datos simulados en memoria.")

    col_table, col_side = st.columns([1.8, 1])

    with col_table:
        st.markdown("### Registros recientes")
        if records.empty:
            st.info("Aún no hay registros.")
        else:
            st.dataframe(
                records[
                    [
                        "employee_name",
                        "branch_name",
                        "movement_type",
                        "status",
                        "hora",
                        "distance_meters",
                        "channel",
                        "justification",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

    with col_side:
        st.markdown("### Exportación")
        st.download_button(
            "Descargar Excel",
            data=export_records_excel(),
            file_name="neoaccess_registros.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        if st.button("Volver al inicio", use_container_width=True):
            st.session_state["current_view"] = "welcome"
            st.session_state["selected_profile"] = None
            st.rerun()

    if not records.empty:
        st.markdown("### Tendencia de asistencia")
        trend = (
            records[records["movement_type"] == "entrada"]
            .groupby("fecha")
            .size()
            .reset_index(name="entradas")
        )
        st.line_chart(trend.set_index("fecha"))

        st.markdown("### Cobertura por sucursal")
        branch_chart = (
            records.groupby("branch_name")
            .size()
            .reset_index(name="registros")
            .sort_values("registros", ascending=False)
        )
        st.bar_chart(branch_chart.set_index("branch_name"))

        st.markdown("### Mapa operativo")
        map_frame = pd.DataFrame(st.session_state["branches"])
        st.map(map_frame.rename(columns={"lat": "LAT", "lon": "LON"}), latitude="LAT", longitude="LON")
