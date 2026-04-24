import os
import sys
import time
import streamlit as st
import pytz
from datetime import datetime
from streamlit_js_eval import get_geolocation

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from services.supabase_client import get_supabase
from services.data import (
    obtener_registros,
    obtener_empleados,
    obtener_sucursales_catalogo,
    enriquecer_con_nombre_sucursal,
    obtener_timezone_sucursal,
    actualizar_registro_justificacion,
    registro_existe,
)
from core.attendance import (
    validar_geocerca,
    existe_registro_duplicado,
    validar_flujo,
    calcular_estatus,
)
from core.reporting import enviar_reporte_diario, normalizar_resultado_envio
from ui.login import render_splash_screen, render_login_form
from ui.kiosk import render_user_panel, render_kiosk_section
from ui.admin import render_admin_dashboard
from config import ROLES_KIOSCO, ROLES_ADMIN

st.set_page_config(page_title="NeoAccess PRO", page_icon="🚀", layout="wide")

supabase = get_supabase()

@st.cache_resource
def get_runtime_state():
    return {"fecha_reporte": None}


def init_state():
    defaults = {
        "user": None,
        "app_stage": "splash",
        "registro_id_actual": None,
        "registro_id_justificar": None,
        "registro_pendiente": None,
        "mostrar_justificacion": False,
        "registro_ok": False,
        "ultimo_movimiento": "",
        "modo_kiosco": False,
        "ultima_geo": None,
        "intentos_login": 0,
        "bloqueado_hasta": None,
        "registro_reciente": False,
        "action_message": None,
        "last_action": None,
        "login_method": "Nombre + PIN",
        "login_auto_pin": None,
        "biometric_ready": False,
        "biometric_user": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_state()


def registrar(nombre, tipo, user, zona_usuario):
    sucursal_id = user.get("sucursal_id")
    if not sucursal_id:
        st.error("❌ No hay sucursal válida")
        return

    ahora = datetime.now(zona_usuario)
    loc = st.session_state.get("ultima_geo")
    if not loc or "coords" not in loc:
        st.warning("Activa ubicación para registrar desde la sucursal")
        return

    lat = loc["coords"]["latitude"]
    lon = loc["coords"]["longitude"]
    ok_geo, msg = validar_geocerca(lat, lon, sucursal_id)
    if not ok_geo:
        st.error(msg)
        return

    valido, motivo = validar_flujo(nombre, tipo)
    if not valido:
        st.warning(motivo)
        if "justificar salida" in motivo.lower():
            st.session_state.mostrar_justificacion = True
        return

    if existe_registro_duplicado(nombre, tipo, ahora):
        st.warning("Registro duplicado detectado")
        return

    try:
        h_ent = datetime.strptime(user["hora_entrada"], "%H:%M:%S").time()
        h_sal = datetime.strptime(user["hora_salida"], "%H:%M:%S").time()
    except Exception:
        st.error("Error leyendo los horarios de entrada/salida")
        return

    est, min_r = calcular_estatus(tipo, ahora, h_ent, h_sal)

    response = supabase.table("registros").insert({
        "empleado": nombre,
        "fecha_hora": ahora.isoformat(),
        "lat": lat,
        "lon": lon,
        "tipo": tipo,
        "estatus": est,
        "min_retardo": min_r,
        "sucursal_id": str(sucursal_id),
        "justificacion": "",
        "horas_extra": False,
    }).execute()

    if getattr(response, "error", None) is not None:
        st.error(f"❌ Error al guardar registro: {response.error}")
        return

    if response.data and len(response.data) > 0:
        nuevo_id = response.data[0].get("id")
    else:
        fallback = supabase.table("registros").select("id").eq("empleado", nombre).eq("fecha_hora", ahora.isoformat()).eq("tipo", tipo).execute()
        nuevo_id = fallback.data[0].get("id") if getattr(fallback, "data", None) and len(fallback.data) > 0 else None

    st.session_state.registro_id_actual = nuevo_id
    st.session_state.registro_id_justificar = nuevo_id
    st.session_state.registro_pendiente = {"nombre": nombre, "tipo": tipo, "fecha_hora": ahora.isoformat()} if nuevo_id is None else None
    st.session_state.registro_ok = True
    st.session_state.ultimo_movimiento = f"{tipo} registrada"
    if est != "A Tiempo":
        st.session_state.mostrar_justificacion = True
    st.session_state.action_message = (
        f"¡{tipo} registrada! Buen turno, {nombre}." if tipo == "Entrada" else f"Salida registrada. Nos vemos pronto, {nombre}."
    )
    st.session_state.last_action = tipo
    st.rerun()


def _resolver_id_justificacion():
    registro_id = st.session_state.get("registro_id_justificar")
    if registro_id:
        return registro_id
    pendiente = st.session_state.get("registro_pendiente")
    if not pendiente:
        return None
    fallback = supabase.table("registros").select("id").eq("empleado", pendiente["nombre"]).eq("fecha_hora", pendiente["fecha_hora"]).eq("tipo", pendiente["tipo"]).execute()
    if getattr(fallback, "data", None) and len(fallback.data) > 0:
        registro_id = fallback.data[0].get("id")
        st.session_state.registro_id_justificar = registro_id
        if registro_id:
            st.session_state.registro_pendiente = None
    return registro_id


def show_app():
    if st.session_state.user is None:
        if st.session_state.app_stage == "splash":
            render_splash_screen()
            st.stop()
        render_login_form()
        st.stop()

    user = st.session_state.user
    if not user:
        render_login_form()
        st.stop()

    tz_sucursal = obtener_timezone_sucursal(user.get("sucursal_id")) or "America/Mexico_City"
    zona_usuario = pytz.timezone(tz_sucursal)

    with st.spinner("📡 Obteniendo ubicación..."):
        time.sleep(0.8)
        geo_actual = get_geolocation()
        if geo_actual and "coords" in geo_actual:
            st.session_state.ultima_geo = geo_actual

    st.markdown("# 🚀 NeoAccess PRO")
    cols = st.columns([3, 1])
    with cols[1]:
        if st.button("🚪 Cerrar sesión"):
            st.session_state.clear()
            st.rerun()

    st.success(f"👤 {user['nombre']} | {user.get('rol', 'empleado').title()} | {user['sucursal_nombre']}")

    if user.get("rol") in ROLES_KIOSCO:
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🖥️ Activar modo kiosco"):
                st.session_state.modo_kiosco = True
                st.rerun()
        with col2:
            if st.button("⛔ Desactivar modo kiosco"):
                st.session_state.modo_kiosco = False
                st.rerun()

    if st.session_state.modo_kiosco and user.get("rol") in ROLES_KIOSCO:
        render_kiosk_section(user, lambda nombre, tipo: registrar(nombre, tipo, user, zona_usuario))
    else:
        render_user_panel(user, lambda nombre, tipo: registrar(nombre, tipo, user, zona_usuario))

    if user.get("rol") in ROLES_ADMIN:
        st.divider()
        render_admin_dashboard(zona_usuario)

    if st.session_state.mostrar_justificacion:
        st.divider()
        registro_id = _resolver_id_justificacion()
        if registro_id:
            st.warning("⚠️ Se requiere justificación")
        elif st.session_state.get("registro_pendiente"):
            st.info("ID de registro pendiente. Escribe el motivo y se intentará guardar en cuanto el registro se confirme.")
        else:
            st.warning("No se encontró el registro para justificar. Por favor registra nuevamente o contacta a soporte.")

        with st.form("form_justificacion"):
            motivo = st.text_area("Escribe el motivo:")
            submitted = st.form_submit_button("Guardar Justificación")
            if submitted:
                registro_id = _resolver_id_justificacion()
                if not registro_id:
                    if st.session_state.get("registro_pendiente"):
                        st.warning("Aún no se ha resuelto el ID del registro. Intenta de nuevo en unos segundos.")
                    else:
                        st.error("❌ No se encontró el registro para justificar.")
                elif not registro_existe(registro_id):
                    st.error("❌ Registro no encontrado. Intenta de nuevo o contacta al administrador.")
                else:
                    res = actualizar_registro_justificacion(registro_id, motivo)
                    if getattr(res, "error", None) is not None:
                        st.error(f"❌ Error de actualización: {res.error}")
                    else:
                        st.success("✅ Justificación guardada")
                        st.session_state.mostrar_justificacion = False
                        st.session_state.registro_id_justificar = None
                        st.session_state.registro_pendiente = None
                        st.rerun()


show_app()
