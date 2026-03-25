import streamlit as st
import pandas as pd
from datetime import datetime, date
from streamlit_js_eval import get_geolocation
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
def distancia(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    a = sin((lat2-lat1)/2)**2 + cos(lat1)*cos(lat2)*sin((lon2-lon1)/2)**2
    return (2 * asin(sqrt(a))) * 6371000

def obtener_registros():
    res = supabase.table("registros").select("*").execute()
    return pd.DataFrame(res.data)

def validar_ubicacion(user):
    loc = get_geolocation()
    if not loc:
        return False, "Activa GPS"

    lat = loc['coords']['latitude']
    lon = loc['coords']['longitude']

    suc = supabase.table("sucursales").select("*").eq("id", user['sucursal_id']).execute().data[0]

    dist = distancia(lat, lon, suc['lat'], suc['lon'])

    if dist <= suc['radio']:
        return True, (lat, lon)

    return False, f"Fuera de sucursal ({int(dist)}m)"

# =========================
# 🔐 SESSION
# =========================
if 'user' not in st.session_state:
    st.session_state.user = None
if 'justificar' not in st.session_state:
    st.session_state.justificar = False
if 'hora_registro' not in st.session_state:
    st.session_state.hora_registro = ""

st.set_page_config(layout="wide")
st.title("🏢 NEOMOTIC Access PRO")

# =========================
# 🔐 LOGIN
# =========================
if not st.session_state.user:

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
            st.success("Bienvenido")
            st.rerun()
        else:
            st.error("Datos incorrectos")

    st.stop()

# =========================
# 👤 USUARIO
# =========================
user = st.session_state.user
st.success(f"👤 {user['nombre']} | Rol: {user.get('rol','empleado')}")

if st.button("Cerrar sesión"):
    st.session_state.user = None
    st.rerun()

# =========================
# 📍 REGISTRO
# =========================
def registrar(tipo):

    ahora = datetime.now(zona)

    ok, ubic = validar_ubicacion(user)

    if not ok:
        st.error(ubic)
        return

    lat, lon = ubic

    # 🔒 BLOQUEO DOBLE
    ultimo = supabase.table("registros")\
        .select("*")\
        .eq("empleado", user['nombre'])\
        .order("fecha_hora", desc=True)\
        .limit(1)\
        .execute()

    if ultimo.data:
        if ultimo.data[0]['tipo'] == tipo:
            st.warning("⚠️ Ya registraste este movimiento")
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

    st.rerun()

st.markdown("## 🕒 Reloj Checador")

col1, col2 = st.columns(2)
col1.button("🟢 ENTRADA", on_click=registrar, args=("Entrada",), use_container_width=True)
col2.button("🔴 SALIDA", on_click=registrar, args=("Salida",), use_container_width=True)

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

                st.success("Guardado")
                st.session_state.justificar = False
                st.rerun()

            else:
                st.error("Escribe más detalle")

# =========================
# 📜 HISTORIAL
# =========================
st.divider()
st.subheader("📜 Mi historial")

df = obtener_registros()

if not df.empty:
    df['fecha_hora'] = pd.to_datetime(df['fecha_hora'])
    df_user = df[df['empleado'] == user['nombre']]
    st.dataframe(df_user.sort_values("fecha_hora", ascending=False))

# =========================
# 🧠 ADMIN / EMPRESA
# =========================
if user.get("rol") == "admin":

    st.divider()
    st.subheader("🏢 Panel empresa")

    df = obtener_registros()

    if not df.empty:

        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'])
        hoy = df[df['fecha_hora'].dt.date == datetime.now().date()]

        # KPIs
        col1, col2 = st.columns(2)
        col1.metric("Registros hoy", len(hoy))
        col2.metric("Retardos", len(hoy[hoy['estatus'].str.contains("Retardo")]))

        st.dataframe(hoy)

        # FALTANTES
        empleados = supabase.table("empleados").select("*").execute().data
        presentes = hoy['empleado'].unique()
        faltantes = [e['nombre'] for e in empleados if e['nombre'] not in presentes]

        st.subheader("🚫 Faltantes")
        for f in faltantes:
            st.error(f)

        # RANKING
        st.subheader("🏆 Ranking puntualidad")
        ranking = df.groupby("empleado")['min_retardo'].sum().sort_values()
        st.bar_chart(ranking)

        # MAPA
        st.subheader("🗺️ Ubicaciones")
        pts = hoy.dropna(subset=['lat', 'lon'])
        if not pts.empty:
            st.map(pts)

        # TENDENCIA
        st.subheader("📊 Tendencia")
        df['dia'] = df['fecha_hora'].dt.date
        st.line_chart(df.groupby('dia').size())

    # =========================
    # 📦 QR MASIVO ZIP
    # =========================
    st.subheader("📦 QR masivo")

    if st.button("Generar QR ZIP"):

        empleados = supabase.table("empleados").select("*").execute().data
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, "w") as z:
            for emp in empleados:
                qr = qrcode.make(emp['nombre'])
                img_bytes = BytesIO()
                qr.save(img_bytes, format='PNG')
                z.writestr(f"{emp['nombre']}.png", img_bytes.getvalue())

        st.download_button("Descargar ZIP", zip_buffer.getvalue(), "QR_empleados.zip")

    # =========================
    # 📦 CARGA MASIVA
    # =========================
    st.subheader("📦 Carga masiva empleados")

    archivo = st.file_uploader("Sube Excel", type=["xlsx"])

    if archivo:
        df_excel = pd.read_excel(archivo)
        st.dataframe(df_excel)

        if st.button("Subir empleados"):

            for _, row in df_excel.iterrows():

                suc = supabase.table("sucursales")\
                    .select("*")\
                    .eq("nombre", row['sucursal'])\
                    .execute()

                if suc.data:
                    supabase.table("empleados").insert({
                        "nombre": row['nombre'],
                        "pin": row['pin'],
                        "activo": True,
                        "rol": row.get('rol', 'empleado'),
                        "sucursal_id": suc.data[0]['id']
                    }).execute()

            st.success("✅ Empleados cargados")
