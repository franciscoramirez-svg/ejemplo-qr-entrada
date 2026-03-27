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
import smtplib
from email.mime.text import MIMEText
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
    R = 6371000
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def validar_geocerca(lat, lon, sucursal_id):
    suc = supabase.table("sucursales").select("*").eq("id", sucursal_id).execute().data
    if not suc: return True
    s = suc[0]
    return distancia_metros(lat, lon, s['lat'], s['lon']) <= s.get("radio", 100)

def validar_flujo(nombre, tipo):
    # Solo consultamos registros del empleado de hoy/ayer para velocidad
    ayer_str = (datetime.now(zona).date() - timedelta(days=1)).isoformat()
    df = pd.DataFrame(supabase.table("registros").select("*").eq("empleado", nombre).gte("fecha_hora", ayer_str).execute().data)
    
    if df.empty: return True, ""
    df['fecha_hora'] = pd.to_datetime(df['fecha_hora'])
    hoy = datetime.now(zona).date()

    if tipo == "Salida":
        hoy_regs = df[df['fecha_hora'].dt.date == hoy]
        if not any(hoy_regs['tipo'] == "Entrada"):
            return False, "⚠️ No puedes registrar SALIDA sin ENTRADA hoy"
    
    return True, ""

# =========================
# 📍 REGISTRAR
# =========================
def registrar(nombre, tipo):
    if st.session_state.registro_ok: return

    ok, msg = validar_flujo(nombre, tipo)
    if not ok:
        st.error(msg)
        return

    # OBTENER GPS REAL
    loc = get_geolocation()
    if not loc:
        st.warning("📍 Esperando GPS... Asegúrate de permitir la ubicación en el navegador.")
        return
    
    lat, lon = loc['coords']['latitude'], loc['coords']['longitude']

    if not validar_geocerca(lat, lon, st.session_state.user['sucursal_id']):
        st.error(f"❌ Fuera de rango (Lat: {lat:.4f}, Lon: {lon:.4f})")
        return

    ahora = datetime.now(zona)
    est, min_r = "A Tiempo", 0

    if tipo == "Entrada":
        h_lim = datetime.strptime(HORA_ENTRADA, "%H:%M:%S").replace(tzinfo=zona).time()
        diff = (datetime.combine(date.today(), ahora.time()) - datetime.combine(date.today(), h_lim)).total_seconds() / 60
        min_r = max(0, int(diff))
        if min_r > 30: est = "RETARDO CRÍTICO"
        elif min_r > 15: est = "Retardo"

    if tipo == "Salida" and ahora.time() < datetime.strptime(HORA_SALIDA, "%H:%M:%S").time():
        est = "SALIDA ANTICIPADA"

    try:
        data_ins = {
            "empleado": nombre, "fecha_hora": ahora.isoformat(), "lat": lat, "lon": lon,
            "tipo": tipo, "estatus": est, "min_retardo": min_r, 
            "sucursal_id": st.session_state.user['sucursal_id'], "justificacion": ""
        }
        res = supabase.table("registros").insert(data_ins).execute()
        st.session_state.registro_id = res.data[0]['id']
        st.session_state.registro_ok = True
        st.session_state.ultimo_movimiento = f"{tipo} registrada ✅"
        if est != "A Tiempo": st.session_state.justificar = True
        st.rerun()
    except Exception as e:
        st.error(f"Error DB: {e}")

# =========================
# 🔐 LOGIN & SESSION
# =========================
for key_s in ['user', 'justificar', 'registro_id', 'modo_kiosco', 'registro_ok', 'ultimo_movimiento']:
    if key_s not in st.session_state: st.session_state[key_s] = None if key_s != 'modo_kiosco' and key_s != 'justificar' and key_s != 'registro_ok' else False

if not st.session_state.user:
    st.title("🏢 NEOMOTIC Access PRO")
    u_input = st.text_input("Nombre")
    p_input = st.text_input("PIN", type="password")
    if st.button("Ingresar"):
        res = supabase.table("empleados").select("*").eq("nombre", u_input).eq("pin", p_input).eq("activo", True).execute()
        if res.data:
            st.session_state.user = res.data[0]
            st.rerun()
        else: st.error("❌ Datos incorrectos")
    st.stop()

# =========================
# 👤 INTERFAZ USUARIO
# =========================
user = st.session_state.user
st.title("🏢 NEOMOTIC Access PRO")
st.sidebar.success(f"👤 {user['nombre']} ({user.get('rol')})")

if st.sidebar.button("🚪 Cerrar sesión"):
    st.session_state.user = None
    st.rerun()

# MODO KIOSCO
if user.get("rol") in ROLES_KIOSCO:
    if st.sidebar.checkbox("🖥️ Activar Modo Kiosco"):
        st.session_state.modo_kiosco = True
    else: st.session_state.modo_kiosco = False

if st.session_state.modo_kiosco:
    st.header("📸 Escanea tu QR")
    foto = st.camera_input("Scanner")
    if foto:
        img = cv2.imdecode(np.asarray(bytearray(foto.getvalue()), dtype=np.uint8), 1)
        qr_data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
        if qr_data:
            st.subheader(f"Empleado: {qr_data}")
            c1, c2 = st.columns(2)
            if c1.button("📥 ENTRADA"): registrar(qr_data, "Entrada")
            if c2.button("📤 SALIDA"): registrar(qr_data, "Salida")
    
    if st.session_state.registro_ok:
        st.success(st.session_state.ultimo_movimiento)
        import time
        time.sleep(3)
        st.session_state.registro_ok = False
        st.rerun()
    st.stop()

# INTERFAZ NORMAL
if not st.session_state.registro_ok:
    c1, c2 = st.columns(2)
    if c1.button("📥 REGISTRAR ENTRADA", use_container_width=True): registrar(user['nombre'], "Entrada")
    if c2.button("📤 REGISTRAR SALIDA", use_container_width=True): registrar(user['nombre'], "Salida")
else:
    st.success(st.session_state.ultimo_movimiento)

# JUSTIFICACIÓN
if st.session_state.justificar and st.session_state.registro_id:
    with st.form("f_just"):
        motivo = st.text_area("⚠️ Explica el motivo del retardo/salida anticipada:")
        if st.form_submit_button("Enviar Justificación"):
            if len(motivo) > 5:
                supabase.table("registros").update({"justificacion": motivo}).eq("id", st.session_state.registro_id).execute()
                st.session_state.justificar = False
                st.success("Guardado"); st.rerun()
            else: st.warning("Por favor detalla más.")

# =========================
# 📊 DASHBOARD ADMIN
# =========================
if user.get("rol") in ROLES_ADMIN:
    st.divider()
    df_hoy = obtener_registros_hoy()
    if not df_hoy.empty:
        st.subheader("📊 Resumen de Hoy")
        df_hoy['fecha_hora'] = pd.to_datetime(df_hoy['fecha_hora']).dt.tz_convert('America/Mexico_City')
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total", len(df_hoy))
        c2.metric("Retardos", len(df_hoy[df_hoy['estatus'].str.contains("Retardo|RETARDO", na=False)]))
        c3.metric("Salidas Ant.", len(df_hoy[df_hoy['estatus']=="SALIDA ANTICIPADA"]))
        
        st.dataframe(df_hoy[["empleado", "fecha_hora", "tipo", "estatus", "justificacion"]].sort_values("fecha_hora", ascending=False))
        
        if st.button("📥 Exportar Reporte de Hoy"):
            output = BytesIO()
            df_hoy.to_excel(output, index=False)
            st.download_button("Descargar Excel", output.getvalue(), "asistencia.xlsx")

    # GENERADOR QR
    st.divider()
    st.subheader("📦 Herramientas QR")
    emps = obtener_empleados()
    sel_emp = st.selectbox("Empleado para QR", [e['nombre'] for e in emps])
    if sel_emp:
        img_qr = qrcode.make(sel_emp)
        buf = BytesIO()
        img_qr.save(buf, format="PNG")
        st.image(buf.getvalue(), width=200)
        st.download_button(f"Descargar QR {sel_emp}", buf.getvalue(), f"QR_{sel_emp}.png")
