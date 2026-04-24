import streamlit as st
import streamlit.components.v1 as components
import qrcode
from io import BytesIO
import cv2
import numpy as np
from datetime import datetime


def _style_kiosk():
    st.markdown(
        """
        <style>
        .action-card {
            background: linear-gradient(135deg, #040d21 0%, #071229 100%);
            border: 1px solid rgba(148, 163, 184, 0.15);
            border-radius: 24px;
            padding: 24px;
            box-shadow: 0 20px 70px rgba(8, 18, 51, 0.2);
            margin-bottom: 24px;
            color: white;
        }
        .big-button button {
            width: 100% !important;
            height: 120px;
            font-size: 1.4rem;
            border-radius: 24px;
            margin: 0.5rem 0;
        }
        .mini-note {
            color: #94a3b8;
            font-size: 0.95rem;
            margin-top: 0.5rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _play_click_sound(tipo):
    frecuencia = 520 if tipo == "Entrada" else 300
    tone = "<script>var ctx = new (window.AudioContext || window.webkitAudioContext)(); var o = ctx.createOscillator(); var g = ctx.createGain(); o.frequency.value = %s; o.type='triangle'; o.connect(g); g.connect(ctx.destination); g.gain.value = 0.12; o.start(); o.stop(ctx.currentTime + 0.18);</script>" % frecuencia
    components.html(tone, height=0)


def render_action_feedback():
    if st.session_state.get("registro_ok") and st.session_state.get("action_message"):
        st.balloons()
        st.success(st.session_state["action_message"])
        if st.session_state.get("last_action"):
            _play_click_sound(st.session_state["last_action"])
            st.session_state["last_action"] = None
        st.session_state["action_message"] = None
        st.session_state["registro_ok"] = False


def render_user_panel(user, registrar):
    _style_kiosk()
    st.markdown("## 🚀 Acceso rápido")
    st.markdown(
        """
        <div class='action-card'>
            <h3>Haz clic en entrada o salida</h3>
            <p class='mini-note'>Recuerda: geolocalización habilitada y solo desde sucursales autorizadas.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    current_time = datetime.now().strftime("%H:%M:%S")
    st.markdown(
        f"""
        <div style="margin-bottom: 24px; display:flex; align-items:center; justify-content:flex-start; gap:16px;">
            <div style="background:#0f172a; padding:14px 20px; border-radius:22px; color:#7dd3fc;">
                <strong style="font-size:1.35rem;">{current_time}</strong><br>
                <span style="font-size:0.85rem;color:#cbd5e1;">Hora actual</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if user.get("faltas_semana") is not None:
        st.info(f"Faltas esta semana: {user['faltas_semana']} ")
    if user.get("cierre_automatico"):
        st.warning(f"Se cerró automáticamente un turno sin salida para las fechas: {', '.join(user['cierre_automatico'])}")

    render_action_feedback()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📥 ENTRADA", key="btn_ent"):
            registrar(user['nombre'], "Entrada")
            st.session_state["last_action"] = "Entrada"
            st.session_state["action_message"] = f"¡Entrada registrada! Buen turno, {user['nombre']}"
    with col2:
        if st.button("📤 SALIDA", key="btn_sal"):
            registrar(user['nombre'], "Salida")
            st.session_state["last_action"] = "Salida"
            st.session_state["action_message"] = f"Salida registrada. Nos vemos pronto, {user['nombre']}"

    if st.session_state.get("ultima_geo") and "coords" in st.session_state.get("ultima_geo"):
        coords = st.session_state["ultima_geo"]["coords"]
        st.caption(f"📍 GPS: {coords['latitude']:.6f}, {coords['longitude']:.6f}")
    else:
        st.warning("Activa ubicación en el navegador para poder registrar.")


def render_kiosk_section(user, registrar):
    _style_kiosk()
    st.markdown("## 🏢 Kiosco QR")
    st.markdown("<p class='mini-note'>Escanea el QR del empleado para registrar entrada o salida en modo kiosco.</p>", unsafe_allow_html=True)

    foto = st.camera_input("📷 Escanea QR")
    if foto:
        img = cv2.imdecode(np.asarray(bytearray(foto.getvalue()), dtype=np.uint8), 1)
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
        if data:
            st.success(f"QR leído: {data}")
            c1, c2 = st.columns(2)
            if c1.button("📥 ENTRADA QR"):
                registrar(data, "Entrada")
                st.session_state["last_action"] = "Entrada"
                st.session_state["action_message"] = f"¡Entrada registrada para {data}!"
            if c2.button("📤 SALIDA QR"):
                registrar(data, "Salida")
                st.session_state["last_action"] = "Salida"
                st.session_state["action_message"] = f"Salida registrada para {data}!"
        else:
            st.warning("No se detectó QR válido. Acerca el código y vuelve a intentar.")
