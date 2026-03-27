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
from streamlit_js_eval import get_geolocation

# =========================
# 🔌 SUPABASE & CONFIG
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

# 🛰️ CAPTURA DE GPS GLOBAL (Para evitar el error de Duplicate Key)
loc_global = get_geolocation()

# 🛰️ CAPTURA DE GPS GLOBAL (Evita bucles infinitos)
if 'location' not in st.session_state:
    st.session_state.location = None

# 🛰️ CAPTURA DE GPS GLOBAL (Solución definitiva para Duplicate Key y TypeError)
loc_data = streamlit_js_eval(
    js_expressions="navigator.geolocation.getCurrentPosition(pos => { window.parent.postMessage({type: 'streamlit:setComponentValue', value: {coords: {latitude: pos.coords.latitude, longitude: pos.coords.longitude}}}, '*') })",
    target_id='get_location_fixed', # Esto actúa como el key único estable
    want_output=True
)


# =========================
# 🧠 FUNCIONES NÚCLEO
# =========================
@st.cache_data(ttl=600)
def obtener_empleados():
    return supabase.table("empleados").select("*").execute().data

def obtener_registros_hoy():
    hoy_str = datetime.now(zona).date().isoformat()
    return pd.DataFrame(supabase.table("registros").select("*").gte("fecha_hora", hoy_str).execute().data)

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
        df = df.dropna(subset=['fecha_hora']) 
        if df.empty: return True, ""
        df['fecha_hora'] = df['fecha_hora'].dt.tz_convert('America/Mexico_City')
        hoy = datetime.now(zona).date()
        if tipo == "Salida":
            hoy_regs = df[df['fecha_hora'].dt.date == hoy]
            if not any(hoy_regs['tipo'] == "Entrada"):
                return False, "⚠️ No puedes registrar SALIDA sin haber registrado ENTRADA hoy."
        return True, ""
    except: return True, ""

# =========================
# 📍 REGISTRAR 
# =========================
def registrar(nombre, tipo):
    if st.session_state.get('registro_ok'): return

    st.subheader(f"📍 Registro de {tipo}")
    
    if not loc_data:
        st.warning("📡 Buscando señal GPS... Por favor permite el acceso en el candado 🔒 y espera un momento.")
        if st.button("🔄 Forzar actualización GPS"): st.rerun()
        return

    try:
        # Extraemos coordenadas del JSON retornado por el JS
        lat = loc_data['coords']['latitude']
        lon = loc_data['coords']['longitude']
        st.success(f"✅ Ubicación detectada: {lat:.5f}, {lon:.5f}")
    except Exception as e:
        st.error("❌ Error al leer coordenadas del sensor."); return

    # --- VALIDACIÓN DE SUCURSAL ---
    res_suc = supabase.table("sucursales").select("*").eq("id", st.session_state.user['sucursal_id']).execute()
    if res_suc.data:
        # Accedemos al primer elemento de la respuesta de Supabase
        s = res_suc.data[0] 
        dist = distancia_metros(lat, lon, s['lat'], s['lon'])
        radio_p = s.get("radio", 1000)

        if dist > radio_p:
            st.error(f"❌ FUERA DE RANGO ({dist:.0f}m)")
            if st.session_state.user.get('rol') in ROLES_ADMIN:
                if not st.checkbox("🔓 OMITIR GEOCERCA (ADMIN)"): return
            else: return
    
    # --- BOTÓN DE CONFIRMACIÓN FINAL ---
    if st.button(f"🚀 CONFIRMAR {tipo.upper()}", use_container_width=True):
        # ... (Tu lógica de guardado en Supabase)
        st.balloons()
        st.rerun()


# =========================
# 🔐 LOGIN & SESSION
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
# 👤 INTERFAZ
# =========================
user = st.session_state.user
st.sidebar.success(f"👤 {user['nombre']} ({user.get('rol')})")
if st.sidebar.button("🚪 Cerrar sesión"):
    st.session_state.user = None
    st.rerun()

if user.get("rol") in ROLES_KIOSCO:
    st.session_state.modo_kiosco = st.sidebar.checkbox("🖥️ Modo Kiosco", value=st.session_state.modo_kiosco)

if st.session_state.modo_kiosco:
    st.header("📸 Escanea tu QR")
    foto = st.camera_input("Scanner")
    if foto:
        img = cv2.imdecode(np.asarray(bytearray(foto.getvalue()), dtype=np.uint8), 1)
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
        if data:
            st.subheader(f"Empleado: {data}")
            c1, c2 = st.columns(2)
            if c1.button("📥 ENTRADA"): registrar(data, "Entrada")
            if c2.button("📤 SALIDA"): registrar(data, "Salida")
    if st.session_state.registro_ok:
        st.success(st.session_state.ultimo_movimiento)
        import time; time.sleep(3)
        st.session_state.registro_ok = False
        st.rerun()
    st.stop()

# INTERFAZ NORMAL
st.title("🏢 NEOMOTIC Access PRO")
if not st.session_state.registro_ok:
    c1, c2 = st.columns(2)
    if c1.button("📥 ENTRADA", use_container_width=True): registrar(user['nombre'], "Entrada")
    if c2.button("📤 SALIDA", use_container_width=True): registrar(user['nombre'], "Salida")
else: st.success(st.session_state.ultimo_movimiento)

if st.session_state.justificar and st.session_state.registro_id:
    with st.form("f_just"):
        mot = st.text_area("⚠️ Justifica tu retardo/salida:")
        if st.form_submit_button("Guardar"):
            if len(mot) > 5:
                supabase.table("registros").update({"justificacion": mot}).eq("id", st.session_state.registro_id).execute()
                st.session_state.justificar = False
                st.rerun()
            else: st.warning("Escribe más detalle.")

# =========================
# 📊 DASHBOARD ADMIN
# =========================
if user.get("rol") in ROLES_ADMIN:
    st.divider()
    st.subheader("📊 Dashboard")
    r = st.selectbox("Rango:", ["Hoy", "Últimos 7 días", "Últimos 30 días"])
    f_inicio = datetime.now(zona).date() - timedelta(days=(0 if r=="Hoy" else 7 if r=="Últimos 7 días" else 30))
    df = pd.DataFrame(supabase.table("registros").select("*").gte("fecha_hora", f_inicio.isoformat()).execute().data)
    
    if not df.empty:
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora']).dt.tz_localize('UTC').dt.tz_convert('America/Mexico_City')
        df['solo_fecha'] = df['fecha_hora'].dt.date
        c1, c2, c3 = st.columns(3)
        c1.metric("Total", len(df))
        c2.metric("Retardos", len(df[df['estatus'].str.contains("Retardo|RETARDO", na=False)]))
        c3.metric("A Tiempo", len(df[df['estatus']=="A Tiempo"]))
        
        st.bar_chart(df.groupby('solo_fecha').size())
        st.dataframe(df[["empleado", "fecha_hora", "tipo", "estatus", "justificacion"]].sort_values("fecha_hora", ascending=False))
        
        out = BytesIO()
        df_e = df.copy()
        for col in df_e.select_dtypes(include=['datetime64[ns, America/Mexico_City]', 'datetimetz']).columns:
            df_e[col] = df_e[col].dt.tz_localize(None)
        with pd.ExcelWriter(out, engine='xlsxwriter') as w: df_e.to_excel(w, index=False)
        st.download_button("📥 Descargar Excel", out.getvalue(), f"reporte_{r}.xlsx")

    # QR TOOLS
    st.divider()
    st.subheader("📦 QR Tools")
    emps = obtener_empleados()
    if emps:
        nombres = [e['nombre'] for e in emps]
        sel = st.selectbox("Generar QR para:", nombres)
        if sel:
            img = qrcode.make(sel)
            b = BytesIO()
            img.save(b, format="PNG")
            st.image(b.getvalue(), width=200)
            st.download_button(f"Descargar QR {sel}", b.getvalue(), f"QR_{sel}.png")

