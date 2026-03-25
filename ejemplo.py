import streamlit as st
import pandas as pd
from datetime import datetime, date
import pytz
from supabase import create_client
import qrcode
from io import BytesIO
import zipfile
import cv2
import numpy as np

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

# =========================
# 🧠 FUNCIONES
# =========================
def obtener_registros():
    return pd.DataFrame(supabase.table("registros").select("*").execute().data)

def obtener_empleados():
    return supabase.table("empleados").select("*").execute().data

def obtener_sucursales():
    return supabase.table("sucursales").select("*").execute().data

# =========================
# 🔐 SESSION
# =========================
if 'user' not in st.session_state:
    st.session_state.user = None
if 'justificar' not in st.session_state:
    st.session_state.justificar = False
if 'hora_registro' not in st.session_state:
    st.session_state.hora_registro = ""
if 'modo_kiosco' not in st.session_state:
    st.session_state.modo_kiosco = False

st.set_page_config(layout="wide")

# =========================
# 🔐 LOGIN
# =========================
if not st.session_state.user:

    st.title("🏢 NEOMOTIC Access PRO")
    nombre = st.text_input("Nombre")
    pin = st.text_input("PIN", type="password")

    if st.button("Ingresar"):
        res = supabase.table("empleados")\
            .select("*")\
            .eq("nombre", nombre)\
            .eq("pin", pin)\
            .eq("activo", True)\
            .execute()

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
st.success(f"👤 {user['nombre']} | {user.get('rol','empleado')}")

# =========================
# 🖥️ KIOSCO CONTROL
# =========================
if user.get("rol") == "admin":
    c1, c2 = st.columns(2)
    if c1.button("🖥️ Activar Kiosco"):
        st.session_state.modo_kiosco = True
    if c2.button("❌ Salir Kiosco"):
        st.session_state.modo_kiosco = False

if st.button("🚪 Cerrar sesión"):
    st.session_state.user = None
    st.rerun()

# =========================
# 📍 REGISTRAR
# =========================
def registrar(nombre, tipo):

    ahora = datetime.now(zona)

    est = "A Tiempo"
    min_r = 0

    if tipo == "Entrada":
        h_lim = datetime.strptime(HORA_ENTRADA, "%H:%M:%S").time()
        diff = (datetime.combine(date.today(), ahora.time()) -
                datetime.combine(date.today(), h_lim)).total_seconds() / 60
        min_r = max(0, int(diff))
        if min_r > 30:
            est = "RETARDO CRÍTICO"
        elif min_r > 15:
            est = "Retardo"

    if tipo == "Salida":
        if ahora.time() < datetime.strptime(HORA_SALIDA,"%H:%M:%S").time():
            est = "SALIDA ANTICIPADA"

    supabase.table("registros").insert({
        "empleado": nombre,
        "fecha_hora": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "lat": 19.24,
        "lon": -96.17,
        "tipo": tipo,
        "estatus": est,
        "min_retardo": min_r,
        "sucursal_id": user['sucursal_id'],
        "justificacion": ""
    }).execute()

    st.success(f"✅ {nombre} - {tipo}")

# =========================
# 🖥️ MODO KIOSCO PRO (QR)
# =========================
if st.session_state.modo_kiosco:

    st.markdown("# 🏢 RELOJ CHECADOR QR")

    foto = st.camera_input("📷 Escanea QR")

    if foto:
        img = cv2.imdecode(np.asarray(bytearray(foto.getvalue()), dtype=np.uint8), 1)
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)

        if data:
            st.success(f"👤 {data}")

            c1, c2 = st.columns(2)
            if c1.button("📥 ENTRADA"):
                registrar(data, "Entrada")

            if c2.button("📤 SALIDA"):
                registrar(data, "Salida")

    st.stop()

# =========================
# 🧾 NORMAL
# =========================
c1, c2 = st.columns(2)
if c1.button("📥 ENTRADA"):
    registrar(user['nombre'], "Entrada")
if c2.button("📤 SALIDA"):
    registrar(user['nombre'], "Salida")

# =========================
# 📊 ADMIN
# =========================
if user.get("rol") == "admin":

    st.divider()
    df = obtener_registros()

    if not df.empty:

        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'])
        hoy = df[df['fecha_hora'].dt.date == datetime.now().date()]

        st.subheader("📊 Dashboard Ejecutivo")

        c1,c2,c3 = st.columns(3)
        c1.metric("Hoy", len(hoy))
        c2.metric("Retardos", len(hoy[hoy['estatus'].str.contains("Retardo")]))
        c3.metric("Faltas", len(obtener_empleados()) - len(hoy['empleado'].unique()))

        st.line_chart(df.groupby(df['fecha_hora'].dt.date).size())

        st.dataframe(hoy)

        # MAPA
        pts = hoy.dropna(subset=['lat','lon'])
        if not pts.empty:
            st.map(pts)

        # =========================
        # 🏢 MULTI SUCURSAL
        # =========================
        sucursales = obtener_sucursales()
        nombres = [s['nombre'] for s in sucursales]

        sel = st.selectbox("Sucursal", nombres)

        if sel:
            suc_id = [s['id'] for s in sucursales if s['nombre']==sel][0]
            st.dataframe(df[df['sucursal_id']==suc_id])

    # =========================
    # 📦 QR ZIP
    # =========================
    if st.button("📦 Generar QR ZIP"):

        empleados = obtener_empleados()
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, "w") as z:
            for emp in empleados:
                qr = qrcode.make(emp['nombre'])
                img_bytes = BytesIO()
                qr.save(img_bytes, format='PNG')
                z.writestr(f"{emp['nombre']}.png", img_bytes.getvalue())

        st.download_button("Descargar ZIP", zip_buffer.getvalue(), "QR.zip")
