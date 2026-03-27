import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import pytz
from supabase import create_client
import qrcode
from io import BytesIO
import zipfile
import cv2
import numpy as np
from math import radians, cos, sin, asin, sqrt
from streamlit_js_eval import streamlit_js_eval

# =========================
# 🔌 CONFIGURACIÓN & SUPABASE
# =========================
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

zona = pytz.timezone('America/Mexico_City')
HORA_ENTRADA = "07:00:00"
HORA_SALIDA = "17:00:00"
ROLES_KIOSCO = ["admin", "Supervisor OP", "Supervisor Seguridad"]
ROLES_ADMIN = ["admin"]

st.set_page_config(layout="wide", page_title="NEOMOTIC Access PRO")

# =========================
# 🧠 FUNCIONES NÚCLEO
# =========================
@st.cache_data(ttl=600)
def obtener_empleados():
    return supabase.table("empleados").select("*").execute().data

def distancia_metros(lat1, lon1, lat2, lon2):
    if None in [lat1, lon1, lat2, lon2]: return 999999
    try:
        R = 6371000
        dlat, dlon = radians(float(lat2) - float(lat1)), radians(float(lon2) - float(lon1))
        a = sin(dlat/2)**2 + cos(radians(float(lat1))) * cos(radians(float(lat2))) * sin(dlon/2)**2
        return 2 * R * asin(sqrt(a))
    except: return 999999

def validar_flujo(nombre, tipo):
    try:
        ayer_str = (datetime.now(zona).date() - timedelta(days=1)).isoformat()
        res = supabase.table("registros").select("*").eq("empleado", nombre).gte("fecha_hora", ayer_str).execute()
        if not res.data: return True, ""
        df = pd.DataFrame(res.data)
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce', utc=True)
        df = df.dropna(subset=['fecha_hora']).copy()
        df['fecha_hora'] = df['fecha_hora'].dt.tz_convert(zona)
        hoy = datetime.now(zona).date()
        if tipo == "Salida" and not any((df['fecha_hora'].dt.date == hoy) & (df['tipo'] == "Entrada")):
            return False, "⚠️ No puedes registrar SALIDA sin haber registrado ENTRADA hoy."
        return True, ""
    except: return True, ""

# =========================
# 📍 REGISTRAR (AUTOMÁTICO & SEGURO)
# =========================
def registrar(nombre, tipo):
    if st.session_state.get('registro_ok'): return

    st.subheader(f"📍 Validando Ubicación para {tipo}...")
    
    # 🛰️ CAPTURA DE GPS (Solo se activa al picar el botón)
    # Usamos una clave única por tipo para evitar el error de Duplicate Key
    loc = streamlit_js_eval(
        js_expressions="navigator.geolocation.getCurrentPosition(pos => { window.parent.postMessage({type: 'streamlit:setComponentValue', value: {coords: {latitude: pos.coords.latitude, longitude: pos.coords.longitude}}}, '*') })",
        want_output=True,
        key=f"gps_{tipo}_{nombre}"
    )

    if not loc:
        st.warning("📡 Obteniendo coordenadas... Por favor, permite el acceso en el candado 🔒 de tu navegador.")
        st.info("Si el mensaje no cambia en 5 segundos, refresca la página.")
        return

    try:
        lat = loc['coords']['latitude']
        lon = loc['coords']['longitude']
    except:
        st.error("❌ Error al leer el sensor GPS."); return

    # --- 🗺️ VALIDACIÓN DE GEOCERCA (ESTRICTA) ---
    res_suc = supabase.table("sucursales").select("*").eq("id", st.session_state.user['sucursal_id']).execute()
    if res_suc.data:
        s = res_suc.data[0]
        dist = distancia_metros(lat, lon, s['lat'], s['lon'])
        radio_p = s.get("radio", 1000)

        if dist > radio_p:
            st.error(f"❌ FUERA DE RANGO: Estás a {dist:.0f}m de la sucursal.")
            # Solo el Admin puede omitir para pruebas
            if st.session_state.user.get('rol') in ROLES_ADMIN:
                if not st.checkbox("🔓 Omitir Geocerca (Solo Admin)"): return
            else: return
        else:
            st.success(f"✅ Ubicación confirmada: estás a {dist:.0f}m.")

    # --- 📝 GUARDADO AUTOMÁTICO TRAS VALIDAR ---
    ahora = datetime.now(zona)
    try:
        data_ins = {
            "empleado": nombre, "fecha_hora": ahora.isoformat(), "lat": lat, "lon": lon,
            "tipo": tipo, "estatus": "A Tiempo", "sucursal_id": st.session_state.user['sucursal_id']
        }
        supabase.table("registros").insert(data_ins).execute()
        st.session_state.registro_ok = True
        st.balloons()
        st.rerun()
    except Exception as e:
        st.error(f"Error al guardar: {e}")

# =========================
# 🔐 LOGIN & SESIÓN
# =========================
for k in ['user', 'justificar', 'registro_id', 'modo_kiosco', 'registro_ok', 'ultimo_movimiento']:
    if k not in st.session_state: st.session_state[k] = False if k in ['modo_kiosco', 'justificar', 'registro_ok'] else None

if not st.session_state.user:
    st.title("🏢 NEOMOTIC Access PRO")
    u, p = st.text_input("Nombre"), st.text_input("PIN", type="password")
    if st.button("Ingresar"):
        res = supabase.table("empleados").select("*").eq("nombre", u).eq("pin", p).eq("activo", True).execute()
        if res.data:
            st.session_state.user = res.data[0]
            st.rerun()
        else: st.error("❌ Datos incorrectos")
    st.stop()

# =========================
# 👤 INTERFAZ PRINCIPAL
# =========================
user = st.session_state.user
st.sidebar.success(f"👤 {user['nombre']}")

if st.sidebar.button("🚪 Cerrar sesión"):
    st.session_state.user = None
    st.rerun()

# MODO KIOSCO
if user.get("rol") in ROLES_KIOSCO:
    st.session_state.modo_kiosco = st.sidebar.checkbox("🖥️ Modo Kiosco", value=st.session_state.modo_kiosco)

if st.session_state.modo_kiosco:
    st.header("📸 Escáner QR")
    foto = st.camera_input("Enfoque su código")
    if foto:
        img = cv2.imdecode(np.asarray(bytearray(foto.getvalue()), dtype=np.uint8), 1)
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
        if data:
            st.subheader(f"Empleado: {data}")
            c1, c2 = st.columns(2)
            if c1.button("📥 ENTRADA"): registrar(data, "Entrada")
            if c2.button("📤 SALIDA"): registrar(data, "Salida")
    st.stop()

# INTERFAZ NORMAL (EMPLEADO)
st.title("🏢 Control de Asistencia")
if not st.session_state.registro_ok:
    c1, c2 = st.columns(2)
    if c1.button("📥 ENTRADA", use_container_width=True): registrar(user['nombre'], "Entrada")
    if c2.button("📤 SALIDA", use_container_width=True): registrar(user['nombre'], "Salida")
else:
    st.success("✅ Registro completado con éxito.")
    if st.button("Hacer otro registro"):
        st.session_state.registro_ok = False
        st.rerun()

# =========================
# 📊 DASHBOARD ADMIN
# =========================
if user.get("rol") in ROLES_ADMIN:
    st.divider(); st.subheader("📊 Dashboard")
    r = st.selectbox("Rango:", ["Hoy", "Últimos 7 días", "Últimos 30 días"])
    f_ini = datetime.now(zona).date() - timedelta(days=(0 if r=="Hoy" else 7 if r=="Últimos 7 días" else 30))
    df = pd.DataFrame(supabase.table("registros").select("*").gte("fecha_hora", f_ini.isoformat()).execute().data)
    if not df.empty:
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora']).dt.tz_localize('UTC').dt.tz_convert(zona)
        st.dataframe(df.sort_values("fecha_hora", ascending=False), use_container_width=True)
        
        out = BytesIO(); df_exc = df.copy()
        for col in df_exc.select_dtypes(include=['datetimetz']).columns: df_exc[col] = df_exc[col].dt.tz_localize(None)
        with pd.ExcelWriter(out, engine='xlsxwriter') as w: df_exc.to_excel(w, index=False)
        st.download_button("📥 Descargar Excel", out.getvalue(), f"reporte_{r}.xlsx")

