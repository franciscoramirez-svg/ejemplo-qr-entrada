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

# =========================
# 🔌 SUPABASE
# =========================
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

# =========================
# ⚙️ CONFIG
# =========================
zona = pytz.timezone('America/Mexico_City')
HORA_ENTRADA = "07:00:00"
HORA_SALIDA = "17:00:00"

ROLES_KIOSCO = ["admin", "Supervisor OP", "Supervisor Seguridad"]
ROLES_ADMIN = ["admin"]

# =========================
# 📡 GEO
# =========================
def distancia_metros(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def validar_geocerca(lat, lon, sucursal_id):
    suc = supabase.table("sucursales").select("*").eq("id", sucursal_id).execute().data
    if not suc:
        return True
    s = suc[0]
    dist = distancia_metros(lat, lon, s['lat'], s['lon'])
    return dist <= s.get("radio", 100)

# =========================
# 🧠 FUNCIONES
# =========================
def obtener_registros():
    df = pd.DataFrame(supabase.table("registros").select("*").execute().data)
    if not df.empty:
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce')
        df = df.dropna(subset=['fecha_hora'])
    return df

def obtener_empleados():
    return supabase.table("empleados").select("*").execute().data

# =========================
# 📧 EMAIL
# =========================
def enviar_alerta(faltantes):
    if not faltantes:
        return
    msg = MIMEText("Faltantes:\n" + "\n".join(faltantes))
    msg['Subject'] = "Asistencia diaria"
    msg['From'] = "tu_correo@gmail.com"
    msg['To'] = "admin@empresa.com"

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login("tu_correo@gmail.com", "TU_PASSWORD")
        server.send_message(msg)
        server.quit()
        st.success("📧 Correo enviado")
    except Exception as e:
        st.error(f"Error correo: {e}")

# =========================
# 🔐 SESSION
# =========================
for key in ["user","justificar","registro_id","modo_kiosco","registro_ok","ultimo_movimiento"]:
    if key not in st.session_state:
        st.session_state[key] = False if key!="user" else None

st.set_page_config(layout="wide")

# =========================
# 🔐 LOGIN
# =========================
if not st.session_state.user:
    st.title("🏢 NEOMOTIC Access PRO")
    nombre = st.text_input("Nombre")
    pin = st.text_input("PIN", type="password")

    if st.button("Ingresar"):
        res = supabase.table("empleados").select("*").eq("nombre", nombre).eq("pin", pin).eq("activo", True).execute()
        if res.data:
            st.session_state.user = res.data[0]
            st.rerun()
        else:
            st.error("❌ Datos incorrectos")
    st.stop()

# =========================
# 👤 USER
# =========================
user = st.session_state.user
st.title("🏢 NEOMOTIC Access PRO")
st.success(f"👤 {user['nombre']} | {user.get('rol')}")

if st.button("🚪 Cerrar sesión"):
    st.session_state.user = None
    st.rerun()

# =========================
# 🖥️ KIOSCO
# =========================
if user.get("rol") in ROLES_KIOSCO:
    col1, col2 = st.columns(2)
    if col1.button("🟢 Activar Kiosco"):
        st.session_state.modo_kiosco = True
    if col2.button("🔴 Salir Kiosco"):
        st.session_state.modo_kiosco = False

# =========================
# 📍 REGISTRAR
# =========================
def registrar(nombre, tipo):

    if st.session_state.registro_ok:
        return

    ahora = datetime.now(zona)

    # GPS (simulado)
    lat, lon = 19.24, -96.17

    if not validar_geocerca(lat, lon, user['sucursal_id']):
        st.error("❌ Fuera de sucursal")
        return

    est = "A Tiempo"
    min_r = 0

    if tipo == "Entrada":
        h = datetime.strptime(HORA_ENTRADA,"%H:%M:%S").time()
        diff = (datetime.combine(date.today(), ahora.time()) - datetime.combine(date.today(), h)).total_seconds()/60
        min_r = max(0,int(diff))
        if min_r>30: est="RETARDO CRÍTICO"
        elif min_r>15: est="Retardo"

    if tipo=="Salida":
        if ahora.time() < datetime.strptime(HORA_SALIDA,"%H:%M:%S").time():
            est="SALIDA ANTICIPADA"

    res = supabase.table("registros").insert({
        "empleado": nombre,
        "fecha_hora": ahora.isoformat(),
        "lat": lat,
        "lon": lon,
        "tipo": tipo,
        "estatus": est,
        "min_retardo": min_r,
        "sucursal_id": user['sucursal_id'],
        "justificacion": "",
        "horas_extra": False
    }).execute()

    st.session_state.registro_id = res.data[0]['id']
    st.session_state.registro_ok = True
    st.session_state.ultimo_movimiento = f"{tipo} registrada"

    st.toast("Registro exitoso", icon="✅")
    st.rerun()

# =========================
# 🖥️ KIOSCO QR
# =========================
if st.session_state.modo_kiosco:

    st.markdown("# 🏢 KIOSCO QR")

    foto = st.camera_input("Escanea QR")

    if foto:
        img = cv2.imdecode(np.asarray(bytearray(foto.getvalue()), dtype=np.uint8), 1)
        data,_,_ = cv2.QRCodeDetector().detectAndDecode(img)

        if data:
            st.success(data)
            if st.button("Entrada"):
                registrar(data,"Entrada")
            if st.button("Salida"):
                registrar(data,"Salida")

    st.stop()

# =========================
# 🧾 NORMAL
# =========================
st.markdown("## Registro")

c1,c2=st.columns(2)
if c1.button("Entrada"):
    registrar(user['nombre'],"Entrada")
if c2.button("Salida"):
    registrar(user['nombre'],"Salida")

# =========================
# 📊 ADMIN
# =========================
if user.get("rol") in ROLES_ADMIN:

    df = obtener_registros()

    if not df.empty:

        hoy = df[df['fecha_hora'].dt.date==date.today()]

        st.subheader("📊 Dashboard")

        c1,c2,c3=st.columns(3)
        c1.metric("Hoy",len(hoy))
        c2.metric("Retardos",len(hoy[hoy['estatus'].str.contains("Retardo",na=False)]))
        c3.metric("Salidas",len(hoy[hoy['tipo']=="Salida"]))

        st.bar_chart(df.groupby(df['fecha_hora'].dt.date).size())

        empleados = obtener_empleados()
        presentes = hoy['empleado'].unique()
        faltantes = [e['nombre'] for e in empleados if e['nombre'] not in presentes]

        st.subheader("Faltantes")
        for f in faltantes:
            st.error(f)

        if st.button("📧 Enviar correo"):
            enviar_alerta(faltantes)

        # =========================
        # 🧾 EXCEL
        # =========================
        output = BytesIO()
        df.to_excel(output,index=False)
        output.seek(0)

        st.download_button("⬇️ Excel",output,"reporte.xlsx")

# =========================
# 📦 QR
# =========================
st.subheader("QR")

emps = obtener_empleados()
if emps:
    sel = st.selectbox("Empleado",[e['nombre'] for e in emps])
    qr = qrcode.make(sel)

    img_bytes = BytesIO()
    qr.save(img_bytes,format='PNG')
    img_bytes.seek(0)

    st.image(img_bytes)

    st.download_button("Descargar",img_bytes.getvalue(),f"{sel}.png")
