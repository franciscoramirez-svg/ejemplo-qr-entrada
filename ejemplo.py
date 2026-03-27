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

# 🔐 ROLES PRO
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

    if dist > s.get("radio", 100):
        return False

    return True

# =========================
# 🧠 FUNCIONES
# =========================
def obtener_registros():
    return pd.DataFrame(supabase.table("registros").select("*").execute().data)

def obtener_empleados():
    return supabase.table("empleados").select("*").execute().data

# =========================
#🧾 EXPORTACIÓN EXCEL
# =========================
def exportar_excel(df):

    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    st.download_button(
        "⬇️ Descargar Excel",
        output,
        file_name="reporte_asistencia.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

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
if 'user' not in st.session_state:
    st.session_state.user = None
if 'justificar' not in st.session_state:
    st.session_state.justificar = False
if 'registro_id' not in st.session_state:
    st.session_state.registro_id = None
if 'modo_kiosco' not in st.session_state:
    st.session_state.modo_kiosco = False
if 'registro_ok' not in st.session_state:
    st.session_state.registro_ok = False
if 'ultimo_movimiento' not in st.session_state:
    st.session_state.ultimo_movimiento = ""

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

# 🔥 FIX ADMIN NO BLOQUEADO
if user.get("rol") in ROLES_ADMIN:
    st.session_state.registro_ok = False

st.title("🏢 NEOMOTIC Access PRO")
st.success(f"👤 {user['nombre']} | {user.get('rol','empleado')}")

# =========================
# 🔘 CONTROLES
# =========================
if st.button("🚪 Cerrar sesión"):
    st.session_state.user = None
    st.rerun()

# 🖥️ CONTROL KIOSCO (MULTI-ROL)
if user.get("rol") in ROLES_KIOSCO:
    st.divider()
    st.subheader("🖥️ Modo Kiosco")

    col1, col2 = st.columns(2)

    if col1.button("🟢 Activar"):
        st.session_state.modo_kiosco = True
        st.rerun()

    if col2.button("🔴 Salir"):
        st.session_state.modo_kiosco = False
        st.rerun()

# =========================
# 🧠 VALIDACIONES
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
            return False, "⚠️ No puedes registrar SALIDA sin ENTRADA"

    if tipo == "Entrada":
        ayer_regs = df[(df['empleado'] == nombre) & (df['fecha_hora'].dt.date == ayer)]

        if any(ayer_regs['tipo'] == "Entrada") and not any(ayer_regs['tipo'] == "Salida"):
            st.session_state.justificar = True
            return False, "⚠️ Debes justificar falta de salida de ayer"

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

    # 📡 GPS REAL (desde navegador)
    loc = st.experimental_get_query_params()

    lat = float(loc.get("lat",[19.24])[0])
    lon = float(loc.get("lon",[-96.17])[0])

    # 🔒 VALIDAR GEO
    if not validar_geocerca(lat, lon, user['sucursal_id']):
        st.error("❌ Fuera de la sucursal")
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

    try:
        response = supabase.table("registros").insert({
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

        if response.data:
            st.session_state.registro_id = response.data[0]['id']
            st.session_state.registro_ok = True
            st.session_state.ultimo_movimiento = f"{tipo} registrada"
        
            if est != "A Tiempo":
                st.session_state.justificar = True

            st.toast(f"{tipo} registrada", icon="✅")
            st.rerun()

    except Exception as e:
        st.error(f"❌ Error al insertar: {e}")

# =========================
# 🖥️ KIOSCO QR
# =========================
if st.session_state.modo_kiosco and user.get("rol") in ROLES_KIOSCO:

    st.markdown("# 🏢 RELOJ CHECADOR QR")

    if st.session_state.registro_ok:

        st.success(f"✅ {st.session_state.ultimo_movimiento}")

        import time
        time.sleep(2)

        st.session_state.registro_ok = False
        st.session_state.ultimo_movimiento = ""

        st.rerun()

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
st.markdown("## 🕒 Reloj Checador")

if st.session_state.registro_ok and user.get("rol") not in ROLES_ADMIN:
    st.success(f"✅ {st.session_state.ultimo_movimiento}")
else:
    c1, c2 = st.columns(2)

    if c1.button("📥 ENTRADA"):
        registrar(user['nombre'], "Entrada")

    if c2.button("📤 SALIDA"):
        registrar(user['nombre'], "Salida")

# =========================
# ⚠️ JUSTIFICACIÓN
# =========================
if st.session_state.justificar:

    st.divider()
    st.warning("⚠️ Se requiere justificación")

    with st.form("just"):
        motivo = st.text_area("Escribe el motivo:")

        if st.form_submit_button("Guardar"):

            if len(motivo) > 4:

                supabase.table("registros").update({
                    "justificacion": motivo
                }).eq("id", st.session_state.registro_id).execute()

                st.success("✅ Justificación guardada")

                st.session_state.justificar = False
                st.session_state.registro_ok = False
                st.rerun()

            else:
                st.error("Escribe más detalle")

# =========================
# 📊 DASHBOARD SOLO ADMIN
# =========================
if user.get("rol") in ROLES_ADMIN:

    st.divider()
    st.subheader("📊 Dashboard Ejecutivo")

    df = obtener_registros()

    if not df.empty:

        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce')
        df = df.dropna(subset=['fecha_hora'])

        hoy = df[df['fecha_hora'].dt.date == datetime.now().date()]

        c1, c2, c3 = st.columns(3)
        c1.metric("Registros hoy", len(hoy))
        c2.metric("Retardos", len(hoy[hoy['estatus'].str.contains("Retardo", na=False)]))
        c3.metric("Salidas anticipadas", len(hoy[hoy['estatus']=="SALIDA ANTICIPADA"]))

        st.dataframe(hoy.sort_values("fecha_hora", ascending=False))

        st.subheader("📈 Tendencia")
        df['dia'] = df['fecha_hora'].dt.date
        
        st.subheader("📊 Análisis visual")

        df['dia'] = df['fecha_hora'].dt.date

        col1, col2 = st.columns(2)

        col1.bar_chart(df.groupby('dia').size())

        col2.bar_chart(df.groupby('empleado')['min_retardo'].sum())


        st.subheader("🗺️ Ubicaciones")
        pts = hoy.dropna(subset=['lat','lon'])
        if not pts.empty:
            st.map(pts)

        empleados = obtener_empleados()
        presentes = hoy['empleado'].unique()

        faltantes = [e['nombre'] for e in empleados if e['nombre'] not in presentes]

        st.subheader("🚫 Faltantes")
        for f in faltantes:
            st.error(f)

    # =========================
    # 🧾 EXPORTAR
    # =========================
    st.subheader("🧾 Exportar datos")
    exportar_excel(df)

# =========================
# 📦 GENERAR QR MASIVO (ADMIN)
# =========================
st.divider()
st.subheader("📦 Generar QR de empleados")

empleados = obtener_empleados()

if empleados:

    nombres_emp = [e['nombre'] for e in empleados]

    st.info(f"Total empleados: {len(nombres_emp)}")

    col1, col2 = st.columns(2)

    # =========================
    # 🔹 DESCARGAR TODOS (ZIP)
    # =========================
    if col1.button("📦 Descargar todos los QR (ZIP)"):

        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, "w") as z:
            for emp in empleados:
                qr = qrcode.make(emp['nombre'])

                img_bytes = BytesIO()
                qr.save(img_bytes, format='PNG')

                z.writestr(f"{emp['nombre']}.png", img_bytes.getvalue())

        st.download_button(
            "⬇️ Descargar ZIP",
            zip_buffer.getvalue(),
            file_name="QR_Empleados.zip",
            mime="application/zip"
        )

    # =========================
    # 🔹 QR INDIVIDUAL
    # =========================
    emp_sel = col2.selectbox("Selecciona empleado", nombres_emp)

    if emp_sel:
        qr = qrcode.make(emp_sel)
        img_bytes = BytesIO()
        qr.save(img_bytes, format='PNG')
        img_bytes.seek(0)

        st.image(img_bytes, caption=f"QR de {emp_sel}")

        img_bytes = BytesIO()
        qr.save(img_bytes, format='PNG')
        img_bytes.seek(0)

        st.download_button(
            "⬇️ Descargar QR individual",
            img_bytes.getvalue(),
            file_name=f"{emp_sel}.png",
            mime="image/png"
        )

else:
    st.warning("No hay empleados registrados")


