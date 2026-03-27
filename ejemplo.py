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
# 🧠 DATA
# =========================
def obtener_registros():
    return pd.DataFrame(supabase.table("registros").select("*").execute().data)

def obtener_empleados():
    return supabase.table("empleados").select("*").execute().data

# =========================
# 🧾 EXPORTAR
# =========================
def exportar_excel(df):
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    st.download_button(
        "⬇️ Descargar Excel",
        data=output.getvalue(),
        file_name="reporte.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# =========================
# 🔐 SESSION
# =========================
for key, val in {
    "user": None,
    "justificar": False,
    "registro_id": None,
    "modo_kiosco": False,
    "registro_ok": False,
    "ultimo_movimiento": ""
}.items():
    if key not in st.session_state:
        st.session_state[key] = val

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

if user.get("rol") in ROLES_ADMIN:
    st.session_state.registro_ok = False

st.title("🏢 NEOMOTIC Access PRO")
st.success(f"{user['nombre']} | {user.get('rol')}")

# =========================
# 🔘 CONTROLES
# =========================
if st.button("Cerrar sesión"):
    st.session_state.user = None
    st.rerun()

if user.get("rol") in ROLES_KIOSCO:
    col1, col2 = st.columns(2)
    if col1.button("Activar kiosco"):
        st.session_state.modo_kiosco = True
    if col2.button("Salir kiosco"):
        st.session_state.modo_kiosco = False

# =========================
# 🧠 VALIDACIÓN
# =========================
def validar_flujo(nombre, tipo):
    df = obtener_registros()

    if df.empty:
        return True, ""

    df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce')
    df = df.dropna(subset=['fecha_hora'])

    hoy = date.today()
    ayer = hoy - timedelta(days=1)

    if tipo == "Salida":
        hoy_regs = df[(df['empleado'] == nombre) & (df['fecha_hora'].dt.date == hoy)]
        if not any(hoy_regs['tipo'] == "Entrada"):
            return False, "Sin entrada previa"

    if tipo == "Entrada":
        ayer_regs = df[(df['empleado'] == nombre) & (df['fecha_hora'].dt.date == ayer)]
        if any(ayer_regs['tipo'] == "Entrada") and not any(ayer_regs['tipo'] == "Salida"):
            st.session_state.justificar = True
            return False, "Falta salida de ayer"

    return True, ""

# =========================
# 📍 REGISTRAR
# =========================
def registrar(nombre, tipo):

    if st.session_state.registro_ok:
        return

    ok, msg = validar_flujo(nombre, tipo)
    if not ok:
        st.error(msg)
        return

    ahora = datetime.now(zona)

    lat, lon = 19.24, -96.17

    if not validar_geocerca(lat, lon, user['sucursal_id']):
        st.error("Fuera de zona")
        return

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

    response = supabase.table("registros").insert({
        "empleado": nombre,
        "fecha_hora": ahora.isoformat(),
        "lat": lat,
        "lon": lon,
        "tipo": tipo,
        "estatus": est,
        "min_retardo": min_r,
        "sucursal_id": user['sucursal_id']
    }).execute()

    st.session_state.registro_id = response.data[0]['id']
    st.session_state.registro_ok = True
    st.session_state.ultimo_movimiento = f"{tipo} registrada"
    st.rerun()

# =========================
# 🖥️ KIOSCO
# =========================
if st.session_state.modo_kiosco:

    st.subheader("Modo kiosco")

    if st.session_state.registro_ok:
        st.success(st.session_state.ultimo_movimiento)
        import time
        time.sleep(2)
        st.session_state.registro_ok = False
        st.rerun()

    foto = st.camera_input("QR")

    if foto:
        img = cv2.imdecode(np.asarray(bytearray(foto.getvalue()), dtype=np.uint8), 1)
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)

        if data:
            c1, c2 = st.columns(2)
            if c1.button("Entrada"):
                registrar(data, "Entrada")
            if c2.button("Salida"):
                registrar(data, "Salida")

    st.stop()

# =========================
# 🧾 NORMAL
# =========================
c1, c2 = st.columns(2)
if c1.button("Entrada"):
    registrar(user['nombre'], "Entrada")
if c2.button("Salida"):
    registrar(user['nombre'], "Salida")

# =========================
# 📊 DASHBOARD
# =========================
if user.get("rol") in ROLES_ADMIN:

    st.divider()
    st.subheader("Dashboard")

    df = obtener_registros()

    if not df.empty:
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce')
        df = df.dropna()

        hoy = df[df['fecha_hora'].dt.date == datetime.now().date()]

        st.metric("Hoy", len(hoy))
        st.dataframe(hoy)

        st.line_chart(df.groupby(df['fecha_hora'].dt.date).size())

        st.subheader("Exportar")
        exportar_excel(df)

# =========================
# 📦 QR
# =========================
st.divider()
st.subheader("Generar QR")

emps = obtener_empleados()

if emps:
    nombres = [e['nombre'] for e in emps]

    if st.button("Descargar ZIP"):
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as z:
            for emp in emps:
                qr = qrcode.make(emp['nombre'])
                img_bytes = BytesIO()
                qr.save(img_bytes, format='PNG')
                z.writestr(f"{emp['nombre']}.png", img_bytes.getvalue())

        st.download_button("Descargar", zip_buffer.getvalue())

    sel = st.selectbox("Empleado", nombres)
    if sel:
        qr = qrcode.make(sel)
        img_bytes = BytesIO()
        qr.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        st.image(img_bytes)
