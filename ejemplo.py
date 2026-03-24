import streamlit as st
import pandas as pd
from datetime import datetime, date
from streamlit_js_eval import get_geolocation
import pytz
from math import radians, cos, sin, asin, sqrt
from supabase import create_client
import zipfile

# --- SUPABASE ---
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

# --- CONFIG ---
zona = pytz.timezone('America/Mexico_City')
HORA_ENTRADA = "07:00:00"
HORA_SALIDA = "17:00:00"

# --- FUNCIONES ---
def distancia(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    a = sin((lat2-lat1)/2)**2 + cos(lat1)*cos(lat2)*sin((lon2-lon1)/2)**2
    return (2 * asin(sqrt(a))) * 6371000

def obtener_registros():
    try:
        res = supabase.table("registros").select("*").execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame()

def validar_ubicacion(user):
    loc = get_geolocation()
    if not loc:
        return False, "Activa GPS"

    lat = loc['coords']['latitude']
    lon = loc['coords']['longitude']

    suc = supabase.table("sucursales")\
        .select("*")\
        .eq("id", user['sucursal_id'])\
        .execute().data[0]

    dist = distancia(lat, lon, suc['lat'], suc['lon'])

    if dist <= suc['radio']:
        return True, (lat, lon)

    return False, f"Fuera de sucursal ({int(dist)}m)"

# --- SESSION STATE ---
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
    st.subheader("🔐 Login empleado")

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
st.success(f"👤 {user['nombre']}")

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

    # ⚠️ evitar duplicado inmediato
    df = obtener_registros()
    if not df.empty:
        ult = df[df['empleado'] == user['nombre']].tail(1)
        if not ult.empty and ult['tipo'].values[0] == tipo:
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

col1, col2 = st.columns(2)
col1.button("📥 ENTRADA", on_click=registrar, args=("Entrada",))
col2.button("📤 SALIDA", on_click=registrar, args=("Salida",))

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

                st.success("✅ Justificación guardada")

                st.session_state.justificar = False
                st.session_state.hora_registro = ""

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
    df_user = df[df['empleado'] == user['nombre']].sort_values("fecha_hora", ascending=False)
    st.dataframe(df_user, use_container_width=True)

# =========================
# 🧠 DASHBOARD EMPRESA
# =========================
st.divider()
with st.expander("🔐 Panel empresa"):

    if st.text_input("Password admin", type="password") == "NEOMOTIC2024":

        df = obtener_registros()

        if df.empty:
            st.warning("Sin datos")
        else:
            df['fecha_hora'] = pd.to_datetime(df['fecha_hora'])

            hoy = df[df['fecha_hora'].dt.date == datetime.now().date()]

            st.subheader("📊 Indicadores")
            st.metric("Registros hoy", len(hoy))
            st.metric("Retardos", len(hoy[hoy['estatus'].str.contains("Retardo", na=False)]))

            st.subheader("📋 Hoy")
            st.dataframe(hoy, use_container_width=True)

            st.subheader("🏆 Ranking puntualidad")
            ranking = df.groupby("empleado")['min_retardo'].sum().sort_values()
            st.bar_chart(ranking)

            st.subheader("🗺️ Ubicaciones")
            pts = hoy.dropna(subset=['lat', 'lon'])
            if not pts.empty:
                st.map(pts)

# =========================
# 📦 CARGA MASIVA
# =========================
st.divider()
st.subheader("📦 Carga masiva de empleados")

archivo = st.file_uploader("Sube Excel", type=["xlsx"])

if archivo:
    df = pd.read_excel(archivo)
    st.dataframe(df)

    if st.button("🚀 Subir empleados"):
        ok, err = 0, 0

        for _, row in df.iterrows():
            try:
                suc = supabase.table("sucursales")\
                    .select("id")\
                    .eq("nombre", row['sucursal'])\
                    .execute()

                if not suc.data:
                    err += 1
                    continue

                supabase.table("empleados").insert({
                    "nombre": row['nombre'],
                    "pin": str(row['pin']),
                    "activo": True,
                    "sucursal_id": suc.data[0]['id']
                }).execute()

                ok += 1
            except:
                err += 1

        st.success(f"✅ {ok} empleados cargados")
        if err:
            st.warning(f"⚠️ {err} errores")


# =========================
# 📦 GENERAR QR MASIVO (ZIP)
# =========================
st.divider()
st.subheader("📦 Generar QR masivos")

if st.button("🎯 Generar TODOS los QR en ZIP"):

    empleados = supabase.table("empleados").select("*").execute().data

    if not empleados:
        st.warning("No hay empleados")
    else:
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, "w") as zf:

            for emp in empleados:
                nombre = emp['nombre']

                qr = qrcode.make(nombre)

                img_buffer = BytesIO()
                qr.save(img_buffer, format="PNG")

                zf.writestr(f"{nombre}.png", img_buffer.getvalue())

        st.download_button(
            "⬇️ Descargar ZIP",
            zip_buffer.getvalue(),
            file_name="QR_Empleados.zip"
        )
