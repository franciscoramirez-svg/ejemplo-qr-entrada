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
st.title("🏢 NEOMOTIC Access PRO")
st.success(f"👤 {user['nombre']} | {user.get('rol','empleado')}")

# =========================
# 🔘 CONTROLES
# =========================
if st.button("🚪 Cerrar sesión"):
    st.session_state.user = None
    st.rerun()

if user.get("rol") == "admin":
    col1, col2 = st.columns(2)
    if col1.button("🖥️ Activar Kiosco"):
        st.session_state.modo_kiosco = True
    if col2.button("❌ Salir Kiosco"):
        st.session_state.modo_kiosco = False

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
            "lat": 19.24,
            "lon": -96.17,
            "tipo": tipo,
            "estatus": est,
            "min_retardo": min_r,
            "sucursal_id": user['sucursal_id'],
            "justificacion": "",
            "horas_extra": False
        }).execute()

        # ✅ GUARDAR ID
        st.session_state.registro_id = response.data[0]['id']

        # ✅ CONTROL PRO
        st.session_state.registro_ok = True
        st.session_state.ultimo_movimiento = f"{tipo} registrada"

        if est != "A Tiempo":
            st.session_state.justificar = True

        st.toast(f"{tipo} registrada correctamente", icon="✅")
        st.rerun()

    except Exception as e:
        st.error(f"❌ Error real: {e}")


# =========================
# 🖥️ KIOSCO QR (FIX PRO)
# =========================
if st.session_state.modo_kiosco:

    st.markdown("# 🏢 RELOJ CHECADOR QR")

    # 🧠 RESET AUTOMÁTICO
    if st.session_state.registro_ok:

        st.success(f"✅ {st.session_state.ultimo_movimiento}")

        # ⏱️ esperar 2 segundos y limpiar
        import time
        time.sleep(2)

        st.session_state.registro_ok = False
        st.session_state.ultimo_movimiento = ""

        st.rerun()

    # =========================
    # ESCANEO QR
    # =========================
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

# SOLO BLOQUEA EMPLEADOS
if st.session_state.registro_ok and user.get("rol") != "admin":

    st.success(f"✅ {st.session_state.ultimo_movimiento}")
    st.info("✔ Registro guardado correctamente")

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
                }).eq("id", st.session_state.registro_id)\
                  .execute()

                st.success("✅ Justificación guardada")

                st.session_state.justificar = False
                st.session_state.registro_ok = False
                st.rerun()

            else:
                st.error("Escribe más detalle")

# =========================
# 📊 ADMIN PANEL (FIX FINAL)
# =========================
if user.get("rol") == "admin":

    st.divider()
    st.subheader("📊 Dashboard Ejecutivo")

    df = obtener_registros()

    if not df.empty:

        # 🔥 FIX FECHAS
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce')
        df = df.dropna(subset=['fecha_hora'])

        hoy = df[df['fecha_hora'].dt.date == datetime.now().date()]

        # =========================
        # KPIs
        # =========================
        c1, c2, c3 = st.columns(3)

        c1.metric("Registros hoy", len(hoy))
        c2.metric("Retardos", len(hoy[hoy['estatus'].str.contains("Retardo", na=False)]))
        c3.metric("Salidas anticipadas", len(hoy[hoy['estatus']=="SALIDA ANTICIPADA"]))

        # =========================
        # TABLA
        # =========================
        st.dataframe(hoy.sort_values("fecha_hora", ascending=False))

        # =========================
        # GRÁFICA
        # =========================
        st.subheader("📈 Tendencia")
        df['dia'] = df['fecha_hora'].dt.date
        st.line_chart(df.groupby('dia').size())

        # =========================
        # MAPA
        # =========================
        st.subheader("🗺️ Ubicaciones")
        pts = hoy.dropna(subset=['lat','lon'])
        if not pts.empty:
            st.map(pts)

        # =========================
        # FALTANTES
        # =========================
        empleados = obtener_empleados()
        presentes = hoy['empleado'].unique()

        faltantes = [e['nombre'] for e in empleados if e['nombre'] not in presentes]

        st.subheader("🚫 Faltantes")
        for f in faltantes:
            st.error(f)
