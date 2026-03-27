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
from streamlit_js_eval import streamlit_js_eval, get_geolocation

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

# 🛰️ CAPTURA DE GPS GLOBAL (Evita el error de Duplicate Key)
# Se ejecuta una sola vez al inicio para que el dato esté disponible en toda la app
loc_data = streamlit_js_eval(
    js_expressions="navigator.geolocation.getCurrentPosition(pos => { window.parent.postMessage({type: 'streamlit:setComponentValue', value: {coords: {latitude: pos.coords.latitude, longitude: pos.coords.longitude}}}, '*') })",
    want_output=True,
    key='gps_global_fixed'
)

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
        # Limpieza de fechas para evitar errores de zona horaria
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce', utc=True)
        df = df.dropna(subset=['fecha_hora']).copy()
        df['fecha_hora'] = df['fecha_hora'].dt.tz_convert(zona)
        
        hoy = datetime.now(zona).date()
        if tipo == "Salida":
            hoy_regs = df[df['fecha_hora'].dt.date == hoy]
            if not any(hoy_regs['tipo'] == "Entrada"):
                return False, "⚠️ No puedes registrar SALIDA sin haber registrado ENTRADA hoy."
        return True, ""
    except: return True, ""

# =========================
# 📍 REGISTRAR (Lógica mejorada)
# =========================
def registrar(nombre, tipo):
    if st.session_state.get('registro_ok'): return

    # 1. 🔍 Verificar GPS
    if not loc_data:
        st.warning("📡 Buscando señal GPS... permite el acceso en el candado 🔒 de tu navegador.")
        if st.button("🔄 Reintentar GPS"): st.rerun()
        return

    try:
        lat, lon = loc_data['coords']['latitude'], loc_data['coords']['longitude']
    except:
        st.error("❌ Error al leer el sensor de ubicación."); return

    # 2. 🧠 Validar Flujo
    ok, msg = validar_flujo(nombre, tipo)
    if not ok:
        st.error(msg); return

    # 3. 🗺️ Validar Geocerca
    res_suc = supabase.table("sucursales").select("*").eq("id", st.session_state.user['sucursal_id']).execute()
    if res_suc.data:
        s = res_suc.data[0]
        dist = distancia_metros(lat, lon, s['lat'], s['lon'])
        radio_p = s.get("radio", 1000)
        if dist > radio_p:
            st.error(f"❌ FUERA DE RANGO: Estás a {dist:.0f}m.")
            if st.session_state.user.get('rol') in ROLES_ADMIN:
                if not st.checkbox("🔓 Omitir Geocerca (Admin)"): return
            else: return

    # 4. 🚀 Botón de Confirmación
    st.success(f"✅ Ubicación detectada ({dist:.0f}m)")
    if st.button(f"🚀 FINALIZAR REGISTRO {tipo.upper()}", use_container_width=True):
        ahora = datetime.now(zona)
        est, min_r = "A Tiempo", 0
        h_lim = datetime.strptime(HORA_ENTRADA, "%H:%M:%S").time()
        
        if tipo == "Entrada":
            diff = (datetime.combine(date.today(), ahora.time()) - datetime.combine(date.today(), h_lim)).total_seconds() / 60
            min_r = max(0, int(diff))
            if min_r > 30: est = "RETARDO CRÍTICO"
            elif min_r > 15: est = "Retardo"
        elif tipo == "Salida":
            if ahora.time() < datetime.strptime(HORA_SALIDA, "%H:%M:%S").time(): est = "SALIDA ANTICIPADA"

        try:
            data_ins = {
                "empleado": nombre, "fecha_hora": ahora.isoformat(), "lat": lat, "lon": lon,
                "tipo": tipo, "estatus": est, "min_retardo": min_r,
                "sucursal_id": st.session_state.user['sucursal_id'], "justificacion": ""
            }
            res = supabase.table("registros").insert(data_ins).execute()
            if res.data:
                st.session_state.registro_id = res.data[0]['id']
                st.session_state.registro_ok = True
                st.session_state.ultimo_movimiento = f"{tipo} registrada con éxito ✅"
                if est != "A Tiempo": st.session_state.justificar = True
                st.balloons()
                st.rerun()
        except Exception as e: st.error(f"❌ Error DB: {e}")

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
# 👤 INTERFAZ PRINCIPAL
# =========================
user = st.session_state.user
st.sidebar.success(f"👤 {user['nombre']} ({user.get('rol')})")
if st.sidebar.button("🚪 Cerrar sesión"):
    st.session_state.user = None
    st.rerun()

# MODO KIOSCO
if user.get("rol") in ROLES_KIOSCO:
    st.session_state.modo_kiosco = st.sidebar.checkbox("🖥️ Modo Kiosco", value=st.session_state.modo_kiosco)

if st.session_state.modo_kiosco:
    st.header("📸 Escanea tu QR")
    foto = st.camera_input("Enfoque el código")
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
        import time; time.sleep(3); st.session_state.registro_ok = False; st.rerun()
    st.stop()

# INTERFAZ NORMAL
st.title("🏢 Control de Asistencia")
if not st.session_state.registro_ok:
    c1, c2 = st.columns(2)
    if c1.button("📥 ENTRADA", use_container_width=True): registrar(user['nombre'], "Entrada")
    if c2.button("📤 SALIDA", use_container_width=True): registrar(user['nombre'], "Salida")
else: st.success(st.session_state.ultimo_movimiento)

if st.session_state.justificar and st.session_state.registro_id:
    with st.form("just"):
        mot = st.text_area("⚠️ Justificación necesaria (Retardo/Salida Anticipada):")
        if st.form_submit_button("Guardar Justificación"):
            if len(mot) > 5:
                supabase.table("registros").update({"justificacion": mot}).eq("id", st.session_state.registro_id).execute()
                st.session_state.justificar = False; st.rerun()
            else: st.warning("Por favor detalla más.")

# =========================
# 📊 DASHBOARD ADMIN (Filtrable)
# =========================
if user.get("rol") in ROLES_ADMIN:
    st.divider()
    st.subheader("📊 Panel de Control Administrativo")
    rango = st.selectbox("Periodo de reporte:", ["Hoy", "Últimos 7 días", "Últimos 30 días"])
    f_inicio = datetime.now(zona).date() - timedelta(days=(0 if rango=="Hoy" else 7 if rango=="Últimos 7 días" else 30))
    
    res_db = supabase.table("registros").select("*").gte("fecha_hora", f_inicio.isoformat()).execute()
    df = pd.DataFrame(res_db.data)
    
    if not df.empty:
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora']).dt.tz_localize('UTC').dt.tz_convert(zona)
        df['solo_fecha'] = df['fecha_hora'].dt.date
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total", len(df))
        col2.metric("Retardos", len(df[df['estatus'].str.contains("Retardo|RETARDO", na=False)]))
        col3.metric("A Tiempo", len(df[df['estatus']=="A Tiempo"]))
        
        st.bar_chart(df.groupby('solo_fecha').size())
        st.dataframe(df[["empleado", "fecha_hora", "tipo", "estatus", "justificacion"]].sort_values("fecha_hora", ascending=False), use_container_width=True)
        
        # EXPORTACIÓN EXCEL (Parche de zona horaria)
        out = BytesIO()
        df_exc = df.copy()
        for col in df_exc.select_dtypes(include=['datetime64[ns, America/Mexico_City]', 'datetimetz']).columns:
            df_exc[col] = df_exc[col].dt.tz_localize(None)
        with pd.ExcelWriter(out, engine='xlsxwriter') as w: df_exc.to_excel(w, index=False)
        st.download_button(f"📥 Bajar Excel ({rango})", out.getvalue(), f"reporte_{rango}.xlsx")

    # QR TOOLS
    st.divider(); st.subheader("📦 Generador de QR")
    emps = obtener_empleados()
    if emps:
        sel = st.selectbox("Empleado para generar QR:", [e['nombre'] for e in emps])
        if sel:
            img = qrcode.make(sel); buf = BytesIO(); img.save(buf, format="PNG")
            st.image(buf.getvalue(), width=200)
            st.download_button(f"Descargar QR de {sel}", buf.getvalue(), f"QR_{sel}.png")
