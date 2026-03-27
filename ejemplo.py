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
# 🔌 CONFIGURACIÓN INICIAL
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
# 🧠 FUNCIONES MEJORADAS
# =========================
@st.cache_data(ttl=600)
def obtener_empleados():
    return supabase.table("empleados").select("*").execute().data

def distancia_metros(lat1, lon1, lat2, lon2):
    if None in [lat1, lon1, lat2, lon2]: return 999999
    R = 6371000
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def validar_flujo(nombre, tipo):
    # Consulta optimizada: solo registros del empleado de los últimos 2 días
    ayer_str = (datetime.now(zona).date() - timedelta(days=1)).isoformat()
    res = supabase.table("registros").select("*").eq("empleado", nombre).gte("fecha_hora", ayer_str).execute()
    if not res.data: return True, ""
    
    df = pd.DataFrame(res.data)
    df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce', utc=True)
    df = df.dropna(subset=['fecha_hora']).copy()
    df['fecha_hora'] = df['fecha_hora'].dt.tz_convert(zona)
    
    hoy = datetime.now(zona).date()
    if tipo == "Salida":
        hoy_regs = df[df['fecha_hora'].dt.date == hoy]
        if not any(hoy_regs['tipo'] == "Entrada"):
            return False, "⚠️ No puedes registrar SALIDA sin ENTRADA hoy"
    return True, ""

# =========================
# 📍 REGISTRAR (Lógica original con Parches de Seguridad)
# =========================
def registrar(nombre, tipo):
    if st.session_state.get('registro_ok'): return

    ok, msg = validar_flujo(nombre, tipo)
    if not ok:
        st.error(msg); return

    # GPS ORIGINAL (El que te funcionaba)
    loc = get_geolocation()
    if not loc:
        st.warning("📡 Buscando señal GPS... permite el acceso en el candado 🔒")
        return

    lat, lon = loc['coords']['latitude'], loc['coords']['longitude']

    # Validar Geocerca
    res_suc = supabase.table("sucursales").select("*").eq("id", st.session_state.user['sucursal_id']).execute()
    if res_suc.data:
        s = res_suc.data[0]
        dist = distancia_metros(lat, lon, s['lat'], s['lon'])
        if dist > s.get("radio", 1000):
            st.error(f"❌ Fuera de rango ({dist:.0f}m)")
            if st.session_state.user.get('rol') in ROLES_ADMIN:
                if not st.checkbox("🔓 Omitir Geocerca (Admin)"): return
            else: return

    ahora = datetime.now(zona)
    est, min_r = "A Tiempo", 0

    if tipo == "Entrada":
        h_lim = datetime.strptime(HORA_ENTRADA, "%H:%M:%S").time()
        diff = (datetime.combine(date.today(), ahora.time()) - datetime.combine(date.today(), h_lim)).total_seconds() / 60
        min_r = max(0, int(diff))
        if min_r > 30: est = "RETARDO CRÍTICO"
        elif min_r > 15: est = "Retardo"
    elif tipo == "Salida":
        if ahora.time() < datetime.strptime(HORA_SALIDA, "%H:%M:%S").time(): est = "SALIDA ANTICIPADA"

    try:
        data = {
            "empleado": nombre, "fecha_hora": ahora.isoformat(), "lat": lat, "lon": lon,
            "tipo": tipo, "estatus": est, "min_retardo": min_r,
            "sucursal_id": st.session_state.user['sucursal_id'], "justificacion": ""
        }
        res = supabase.table("registros").insert(data).execute()
        st.session_state.registro_id = res.data[0]['id']
        st.session_state.registro_ok = True
        st.session_state.ultimo_movimiento = f"{tipo} registrada ✅"
        if est != "A Tiempo": st.session_state.justificar = True
        st.rerun()
    except Exception as e: st.error(f"Error: {e}")

# =========================
# 🔐 SESIÓN Y LOGIN
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

if user.get("rol") in ROLES_KIOSCO:
    st.session_state.modo_kiosco = st.sidebar.checkbox("🖥️ Modo Kiosco", value=st.session_state.modo_kiosco)

if st.session_state.modo_kiosco:
    st.header("📸 Escáner QR")
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
        mot = st.text_area("⚠️ Justificación necesaria:")
        if st.form_submit_button("Guardar"):
            supabase.table("registros").update({"justificacion": mot}).eq("id", st.session_state.registro_id).execute()
            st.session_state.justificar = False; st.rerun()

# =========================
# 📊 DASHBOARD ADMIN (Mejorado)
# =========================
if user.get("rol") in ROLES_ADMIN:
    st.divider()
    st.subheader("📊 Dashboard Administrativo")
    r = st.selectbox("Rango:", ["Hoy", "Últimos 7 días", "Últimos 30 días"])
    f_ini = datetime.now(zona).date() - timedelta(days=(0 if r=="Hoy" else 7 if r=="Últimos 7 días" else 30))
    
    res_db = supabase.table("registros").select("*").gte("fecha_hora", f_ini.isoformat()).execute()
    df = pd.DataFrame(res_db.data)
    
    if not df.empty:
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora']).dt.tz_localize('UTC').dt.tz_convert(zona)
        df['solo_fecha'] = df['fecha_hora'].dt.date
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Registros", len(df))
        c2.metric("Retardos", len(df[df['estatus'].str.contains("Retardo|RETARDO", na=False)]))
        c3.metric("A Tiempo", len(df[df['estatus']=="A Tiempo"]))
        
        st.bar_chart(df.groupby('solo_fecha').size())
        st.dataframe(df[["empleado", "fecha_hora", "tipo", "estatus", "justificacion"]].sort_values("fecha_hora", ascending=False), use_container_width=True)
        
        # Exportar Excel Pro
        buffer = BytesIO()
        df_exc = df.copy()
        for col in df_exc.select_dtypes(include=['datetime64[ns, America/Mexico_City]', 'datetimetz']).columns:
            df_exc[col] = df_exc[col].dt.tz_localize(None)
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as w: df_exc.to_excel(w, index=False)
        st.download_button("📥 Descargar Reporte Excel", buffer.getvalue(), f"reporte_{r}.xlsx")

    # QR Tools (Original funcional)
    st.divider(); st.subheader("📦 Generador de QR")
    emps = obtener_empleados()
    if emps:
        sel = st.selectbox("Empleado:", [e['nombre'] for e in emps])
        if sel:
            img = qrcode.make(sel); b = BytesIO(); img.save(b, format="PNG")
            st.image(b.getvalue(), width=200)
            st.download_button(f"Bajar QR {sel}", b.getvalue(), f"QR_{sel}.png")
