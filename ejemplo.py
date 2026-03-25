import streamlit as st
import pandas as pd
from datetime import datetime, date
import pytz
from math import radians, cos, sin, asin, sqrt
from supabase import create_client
import qrcode
from io import BytesIO
import zipfile

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
    res = supabase.table("registros").select("*").execute()
    return pd.DataFrame(res.data)

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
    st.subheader("🔐 Login")

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
            st.success("✅ Bienvenido")
            st.rerun()
        else:
            st.error("❌ Datos incorrectos")

    st.stop()

# =========================
# 👤 USUARIO
# =========================
user = st.session_state.user

st.title("🏢 NEOMOTIC Access PRO")
st.success(f"👤 {user['nombre']} | {user.get('rol','empleado')}")

# =========================
# 🖥️ CONTROL KIOSCO (MEJORADO)
# =========================
if user.get("rol") == "admin":

    col1, col2 = st.columns(2)

    if col1.button("🖥️ Activar Kiosco"):
        st.session_state.modo_kiosco = True

    if col2.button("❌ Salir Kiosco"):
        st.session_state.modo_kiosco = False

# =========================
# 🚪 LOGOUT
# =========================
if st.button("🚪 Cerrar sesión"):
    st.session_state.user = None
    st.rerun()

# =========================
# 📍 REGISTRO
# =========================
def registrar(tipo):

    ahora = datetime.now(zona)

    # 🔥 MODO PRUEBA (sin GPS)
    lat, lon = 19.24, -96.17

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
        h_sal = datetime.strptime(HORA_SALIDA, "%H:%M:%S").time()
        if ahora.time() < h_sal:
            est = "SALIDA ANTICIPADA"

    supabase.table("registros").insert({
        "empleado": user['nombre'],
        "fecha_hora": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "lat": lat,
        "lon": lon,
        "tipo": tipo,
        "estatus": est,
        "min_retardo": min_r,
        "sucursal_id": user['sucursal_id'],
        "justificacion": ""
    }).execute()

    st.success(f"✅ {tipo} registrada")

    if est != "A Tiempo":
        st.session_state.justificar = True
        st.session_state.hora_registro = ahora.strftime("%Y-%m-%d %H:%M:%S")

# =========================
# 🖥️ MODO KIOSCO (LIMPIO)
# =========================
if st.session_state.modo_kiosco:

    st.markdown("# 🏢 RELOJ CHECADOR")
    st.markdown("## Presiona para registrar")

    c1, c2 = st.columns(2)

    if c1.button("📥 ENTRADA", use_container_width=True):
        registrar("Entrada")

    if c2.button("📤 SALIDA", use_container_width=True):
        registrar("Salida")

    st.stop()  # 🔥 BLOQUEA TODO LO DEMÁS

# =========================
# 🧾 MODO NORMAL
# =========================
st.markdown("## 🕒 Registro")

c1, c2 = st.columns(2)

if c1.button("📥 ENTRADA"):
    registrar("Entrada")

if c2.button("📤 SALIDA"):
    registrar("Salida")

# =========================
# ⚠️ JUSTIFICACIÓN
# =========================
if st.session_state.justificar:

    st.divider()

    with st.form("just"):
        motivo = st.text_area("Justificación requerida")

        if st.form_submit_button("Guardar"):
            if len(motivo) > 4:

                supabase.table("registros").update({
                    "justificacion": motivo
                }).eq("empleado", user['nombre'])\
                  .eq("fecha_hora", st.session_state.hora_registro)\
                  .execute()

                st.success("✅ Guardado")
                st.session_state.justificar = False

            else:
                st.error("Escribe más detalle")

# =========================
# 📜 SOLO ADMIN
# =========================
if user.get("rol") == "admin":

    st.divider()
    st.subheader("🏢 Panel Empresa")

    df = obtener_registros()

    if not df.empty:

        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'])
        hoy = df[df['fecha_hora'].dt.date == datetime.now().date()]

        c1, c2, c3 = st.columns(3)
        c1.metric("Registros hoy", len(hoy))
        c2.metric("Retardos", len(hoy[hoy['estatus'].str.contains("Retardo")]))
        c3.metric("Salidas anticipadas", len(hoy[hoy['estatus']=="SALIDA ANTICIPADA"]))

        st.dataframe(hoy)

        empleados = obtener_empleados()
        presentes = hoy['empleado'].unique()
        faltantes = [e['nombre'] for e in empleados if e['nombre'] not in presentes]

        st.subheader("🚫 Faltantes")
        for f in faltantes:
            st.error(f)

        st.subheader("🏆 Ranking")
        ranking = df.groupby("empleado")['min_retardo'].sum().sort_values()
        st.bar_chart(ranking)

        st.subheader("🗺️ Ubicaciones")
        pts = hoy.dropna(subset=['lat', 'lon'])
        if not pts.empty:
            st.map(pts)

    # =========================
    # 📦 QR ZIP
    # =========================
    st.subheader("📦 QR empleados")

    if st.button("Generar ZIP"):

        empleados = obtener_empleados()
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, "w") as z:
            for emp in empleados:
                qr = qrcode.make(emp['nombre'])
                img_bytes = BytesIO()
                qr.save(img_bytes, format='PNG')
                z.writestr(f"{emp['nombre']}.png", img_bytes.getvalue())

        st.download_button("Descargar ZIP", zip_buffer.getvalue(), "QR_empleados.zip")

    # =========================
    # 🏢 SUCURSALES
    # =========================
    st.subheader("🏢 Sucursales")

    sucursales = obtener_sucursales()
    nombres = [s['nombre'] for s in sucursales]

    sel = st.selectbox("Selecciona sucursal", nombres)

    if sel:
        suc_id = [s['id'] for s in sucursales if s['nombre']==sel][0]
        df_suc = df[df['sucursal_id']==suc_id]
        st.dataframe(df_suc)
