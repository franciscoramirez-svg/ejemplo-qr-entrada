from __future__ import annotations

import streamlit as st


def render_kiosk_mode() -> None:
    st.markdown(
        """
        <div class="section-header">
            <div>
                <p class="eyebrow">Modo kiosco</p>
                <h2>Acceso rápido para sucursal</h2>
                <p>Pensado para lector QR, cámara fija o check-in compartido en recepción.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info("Este módulo quedó listo como punto de expansión para QR, cámara dedicada o login express.")

    kiosk_cols = st.columns(3)
    kiosk_cols[0].button("Escanear QR", use_container_width=True)
    kiosk_cols[1].button("Capturar rostro", use_container_width=True)
    if kiosk_cols[2].button("Volver al inicio", use_container_width=True):
        st.session_state["current_view"] = "welcome"
        st.session_state["selected_profile"] = None
        st.rerun()
