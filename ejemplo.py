import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, date
from streamlit_js_eval import get_geolocation
import cv2
import numpy as np
from math import radians, cos, sin, asin, sqrt
import pytz
import qrcode
from io import BytesIO
from supabase import create_client

# --- SUPABASE ---
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

# --- CONFIG ---
zona_veracruz = pytz.timezone('America/Mexico_City')

HORA_ENTRADA_OFICIAL = "07:00:00" 
HORA_SALIDA_OFICIAL = "17:00:00" 
UMBRAL_RETARDO_MINUTOS = 15

OFICINA_LAT = 19.245304  
OFICINA_LON = -96.174232 
RADIO_PERMITIDO = 1000   

# --- FUNCIONES ---
def obtener_registros():
    try:
        response = supabase.table("registros").select("*").execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Error: {e}")
        return pd.DataFrame()

def calcular_distancia(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    a = sin((lat2-lat1)/2)**2 + cos(lat1)*cos(lat2)*sin((lon2-lon1)/2)**2
    return (2 * asin(sqrt(a))) * 6371000

# --- APP ---
st.set_page_config(page_title="NEOMOTIC Access", layout="wide")
ahora = datetime.now(zona_veracruz)

# --- SESSION STATE ---
if 'procesando' not in st.session_state: st.session_state.procesando = False
if 'necesita_justificar' not in st.session_state: st.session_state.necesita_justificar = False
if 'ubicacion_ok' not in st.session_state: st.session_state.ubicacion_ok = False
if 'ultimo_empleado' not in st.session_state: st.session_state.ultimo_empleado = ""
if 'ultima_hora' not in st.session_state: st.session_state.ultima_hora = ""

st.title("📍 Asistencia Personal TRV")

# --- GPS ---
if not st.session_state.ubicacion_ok:
    loc = get_geolocation()
    if not loc:
        st.warning("Activa GPS")
        st.stop()

    lat = loc['coords']['latitude']
    lon = loc['coords']['longitude']
    dist = calcular_distancia(lat, lon, OFICINA_LAT, OFICINA_LON)

    if dist <= RADIO_PERMITIDO:
        st.session_state.ubicacion_ok = True
        st.session_state.lat_act = lat
        st.session_state.lon_act = lon
        st.session_state.dist_actual = dist
        st.rerun()
    else:
        st.error("Fuera de rango")
        st.stop()

# --- INTERFAZ ---
if st.session_state.ubicacion_ok:
    st.success("Ubicación validada")

    foto = st.camera_input("Escanea QR")

    if st.button("🔄 Limpiar cámara"):
        st.session_state.procesando = False
        st.session_state.necesita_justificar = False
        st.session_state.ultimo_empleado = ""
        st.session_state.ultima_hora = ""
        st.rerun()

    if foto and not st.session_state.procesando:
        img = cv2.imdecode(np.asarray(bytearray(foto.getvalue()), dtype=np.uint8), 1)
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)

        if data:
            st.subheader(f"Empleado: {data}")

            def registrar(tipo):
                ahora = datetime.now(zona_veracruz)
                st.session_state.procesando = True

                est, min_r = "A Tiempo", 0

                if tipo == "Entrada":
                    h_lim = datetime.strptime(HORA_ENTRADA_OFICIAL, "%H:%M:%S").time()
                    diff = (datetime.combine(date.today(), ahora.time()) -
                            datetime.combine(date.today(), h_lim)).total_seconds() / 60
                    min_r = max(0, int(diff))

                    if min_r > 30:
                        est = "RETARDO CRÍTICO"
                    elif min_r > UMBRAL_RETARDO_MINUTOS:
                        est = "Retardo"

                elif tipo == "Salida":
                    h_sal = datetime.strptime(HORA_SALIDA_OFICIAL, "%H:%M:%S").time()
                    if ahora.time() < h_sal:
                        est = "SALIDA ANTICIPADA"
                    else:
                        est = "Salida a Tiempo"

                try:
                    supabase.table("registros").insert({
                        "empleado": data,
                        "fecha_hora": ahora.strftime("%Y-%m-%d %H:%M:%S"),
                        "lat": st.session_state.lat_act,
                        "lon": st.session_state.lon_act,
                        "tipo": tipo,
                        "estatus": est,
                        "min_retardo": min_r,
                        "justificacion": ""
                    }).execute()

                    st.success("✅ Registrado")

                    # 👉 ACTIVAR JUSTIFICACIÓN SOLO SI APLICA
                    if est in ["RETARDO CRÍTICO", "Retardo", "SALIDA ANTICIPADA"]:
                        st.session_state.necesita_justificar = True
                        st.session_state.ultimo_empleado = data
                        st.session_state.ultima_hora = ahora.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        st.session_state.necesita_justificar = False

                    st.session_state.procesando = False
                    st.rerun()

                except Exception as e:
                    st.error(f"Error: {e}")

            col1, col2 = st.columns(2)
            col1.button("📥 ENTRADA", on_click=registrar, args=("Entrada",))
            col2.button("📤 SALIDA", on_click=registrar, args=("Salida",))

# --- JUSTIFICACIÓN ---
if st.session_state.necesita_justificar and st.session_state.ultimo_empleado:

    st.divider()

    with st.form("form_j"):
        st.warning(f"⚠️ JUSTIFICACIÓN: {st.session_state.ultimo_empleado}")
        motivo = st.text_area("Motivo:")

        if st.form_submit_button("Guardar"):
            if len(motivo) > 4:
                try:
                    supabase.table("registros").update({
                        "justificacion": motivo
                    }).eq("empleado", st.session_state.ultimo_empleado)\
                      .eq("fecha_hora", st.session_state.ultima_hora)\
                      .execute()

                    st.success("✅ Justificación guardada")

                    # 🔥 RESET TOTAL
                    st.session_state.necesita_justificar = False
                    st.session_state.ultimo_empleado = ""
                    st.session_state.ultima_hora = ""
                    st.session_state.procesando = False

                    st.rerun()

                except Exception as e:
                    st.error(e)
            else:
                st.error("Escribe un motivo válido")

# --- ADMIN ---
st.divider()
with st.expander("🔐 Administración"):

if st.text_input("Password", type="password") == "NEOMOTIC2024":

    df = obtener_registros()

    if df.empty:
        st.warning("Sin registros aún")
        st.stop()

    df['fecha_hora'] = pd.to_datetime(df['fecha_hora'])
    hoy = datetime.now(zona_veracruz).date()
    df_hoy = df[df['fecha_hora'].dt.date == hoy]

    # ========================
    # 📊 KPIs
    # ========================
    total = len(df_hoy)
    entradas = len(df_hoy[df_hoy['tipo'] == 'Entrada'])
    retardos = len(df_hoy[df_hoy['estatus'].isin(["Retardo", "RETARDO CRÍTICO"])])
    incidencias = len(df_hoy[df_hoy['estatus'].isin(["RETARDO CRÍTICO", "SALIDA ANTICIPADA"])])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("👥 Registros", total)
    c2.metric("📥 Entradas", entradas)
    c3.metric("⏱️ Retardos", retardos)
    c4.metric("⚠️ Incidencias", incidencias)

    st.divider()

    # ========================
    # 📈 GRÁFICAS
    # ========================
    st.subheader("📈 Entradas vs Salidas")
    graf = df_hoy['tipo'].value_counts()
    st.bar_chart(graf)

    st.subheader("📊 Estatus")
    graf2 = df_hoy['estatus'].value_counts()
    st.bar_chart(graf2)

    st.divider()

    # ========================
    # 🧾 LISTA DE EMPLEADOS
    # ========================
    st.subheader("👥 Lista de empleados")

    lista_texto = st.text_area("Pega lista (uno por línea)")

    lista_empleados = [e.strip() for e in lista_texto.split("\n") if e.strip()]

    # ========================
    # ❌ FALTANTES
    # ========================
    if lista_empleados:
        llegaron = df_hoy[df_hoy['tipo'] == 'Entrada']['empleado'].unique()
        faltan = [e for e in lista_empleados if e not in llegaron]

        st.subheader("🚫 No han llegado hoy")

        if faltan:
            for f in faltan:
                st.error(f"❌ {f}")
        else:
            st.success("✅ Todos han llegado")

    st.divider()

    # ========================
    # 🥇 RANKING PUNTUALIDAD
    # ========================
    st.subheader("🥇 Ranking puntualidad")

    ranking = df[df['tipo'] == 'Entrada'].groupby('empleado')['min_retardo'].mean().reset_index()
    ranking = ranking.sort_values(by='min_retardo')

    st.dataframe(ranking, use_container_width=True)

    st.divider()

    # ========================
    # 🚨 TOP RETARDOS
    # ========================
    st.subheader("🚨 Top retardos")

    top_retardos = df[df['tipo'] == 'Entrada'].sort_values(by='min_retardo', ascending=False).head(10)

    st.dataframe(top_retardos[['empleado', 'fecha_hora', 'min_retardo']], use_container_width=True)

    st.divider()

    # ========================
    # 📋 TABLA GENERAL
    # ========================
    st.subheader("📋 Registros de hoy")

    df_view = df_hoy.copy()
    df_view['fecha_hora'] = df_view['fecha_hora'].dt.strftime("%d/%m/%Y %H:%M:%S")

    st.dataframe(
        df_view[['empleado', 'fecha_hora', 'tipo', 'estatus', 'justificacion']],
        use_container_width=True
    )

    st.divider()

    # ========================
    # 🗺️ MAPA
    # ========================
    st.subheader("🗺️ Ubicaciones")

    pts = df_hoy.dropna(subset=['lat', 'lon'])
    if not pts.empty:
        st.map(pts)
    else:
        st.info("Sin ubicaciones hoy")    
