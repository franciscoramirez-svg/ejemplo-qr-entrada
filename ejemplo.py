import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime, timedelta, date
from streamlit_js_eval import get_geolocation
# Importaciones para cámara y QR
import cv2
import numpy as np
import pytz
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import qrcode
from io import BytesIO
from math import radians, cos, sin, asin, sqrt

# --- 1. CONFIGURACIÓN INICIAL ---
zona_veracruz = pytz.timezone('America/Mexico_City')
conn = st.connection("gsheets", type=GSheetsConnection)

HORA_ENTRADA_OFICIAL = "07:00:00" 
HORA_SALIDA_OFICIAL = "17:00:00" 
UMBRAL_RETARDO_MINUTOS = 15

OFICINA_LAT = 19.245304  
OFICINA_LON = -96.174232 
RADIO_PERMITIDO = 1000   

# --- 2. FUNCIÓN DE REGISTRO REFORZADA ---
def registrar(tipo, empleado_id, lat, lon):
    ahora_local = datetime.now(zona_veracruz)
    if st.session_state.get('procesando', False):
        return
    
    st.session_state.procesando = True
    try:
        df_full = conn.read(ttl=0)
        hoy_str = ahora_local.strftime("%d/%m/%Y")
        regs_hoy = df_full[(df_full['Empleado'] == empleado_id) & (df_full['Hora'].str.contains(hoy_str))]

        # Validaciones de flujo
        if tipo == "Entrada" and "Entrada" in regs_hoy['Tipo'].values:
            st.warning(f"⚠️ {empleado_id}, ya registraste ENTRADA hoy.")
            return
        if tipo == "Salida":
            if "Entrada" not in regs_hoy['Tipo'].values:
                st.error(f"❌ {empleado_id}, falta registro de ENTRADA.")
                return
            if "Salida" in regs_hoy['Tipo'].values:
                st.warning(f"⚠️ {empleado_id}, ya registraste SALIDA hoy.")
                return

        # Estatus y Retardos
        est, min_r = "A Tiempo", 0
        h_ent = datetime.strptime(HORA_ENTRADA_OFICIAL, "%H:%M:%S").time()
        h_sal = datetime.strptime(HORA_SALIDA_OFICIAL, "%H:%M:%S").time()
        
        if tipo == "Entrada":
            diff = (datetime.combine(date.today(), ahora_local.time()) - datetime.combine(date.today(), h_ent)).total_seconds() / 60
            min_r = max(0, int(diff))
            est = "RETARDO CRÍTICO" if min_r > 30 else ("Retardo" if min_r > UMBRAL_RETARDO_MINUTOS else "A Tiempo")
        else:
            est = "SALIDA ANTICIPADA" if ahora_local.time() < h_sal else "Salida a Tiempo"

        # Guardar en GSheets
        nuevo = pd.DataFrame([[empleado_id, ahora_local.strftime("%d/%m/%Y %H:%M:%S"), lat, lon, tipo, est, min_r, ""]], 
                             columns=["Empleado", "Hora", "Lat", "Lon", "Tipo", "Estatus", "Min_Retardo", "Justificacion"])
        conn.update(data=pd.concat([df_full, nuevo], ignore_index=True))

        # Activar Justificación
        if est in ["RETARDO CRÍTICO", "Retardo", "SALIDA ANTICIPADA"]:
            st.session_state.necesita_justificar = True
            st.session_state.ultimo_empleado = empleado_id
            st.session_state.ultima_hora = ahora_local.strftime("%d/%m/%Y %H:%M:%S")
        
        st.success(f"✅ {tipo} registrada para {empleado_id}")
    except Exception as e:
        st.error(f"Error: {e}")
    finally:
        st.session_state.procesando = False

def calcular_distancia(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    a = sin((lat2-lat1)/2)**2 + cos(lat1) * cos(lat2) * sin((lon2-lon1)/2)**2
    return (2 * asin(sqrt(a))) * 6371000 

# --- 3. INTERFAZ ---
st.set_page_config(page_title="NEOMOTIC Access", layout="wide")
ahora = datetime.now(zona_veracruz)
if 'procesando' not in st.session_state: st.session_state.procesando = False

st.title("📍 Asistencia Personal TRV")
loc = get_geolocation()

if loc:
    lat_act, lon_act = loc['coords']['latitude'], loc['coords']['longitude']
    dist = calcular_distancia(lat_act, lon_act, OFICINA_LAT, OFICINA_LON)
    
    if dist <= RADIO_PERMITIDO:
        foto = st.camera_input("Escanea tu QR")
        if foto:
            img = cv2.imdecode(np.asarray(bytearray(foto.getvalue()), dtype=np.uint8), 1)
            data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
            
            if data:
                st.subheader(f"Empleado: {data}")
                c1, c2 = st.columns(2)
                c1.button("📥 ENTRADA", on_click=registrar, args=("Entrada", data, lat_act, lon_act), use_container_width=True)
                c2.button("📤 SALIDA", on_click=registrar, args=("Salida", data, lat_act, lon_act), use_container_width=True)

                # Bloque de Justificación
                if st.session_state.get('necesita_justificar', False):
                    with st.form("form_j"):
                        st.warning(f"⚠️ {st.session_state.ultimo_empleado}, justifica la incidencia:")
                        motivo = st.text_input("Motivo:")
                        if st.form_submit_button("Guardar Justificación"):
                            df_j = conn.read(ttl=0)
                            mask = (df_j['Empleado'] == st.session_state.ultimo_empleado) & (df_j['Hora'] == st.session_state.ultima_hora)
                            df_j.loc[mask, 'Justificacion'] = motivo
                            conn.update(data=df_j)
                            st.session_state.necesita_justificar = False
                            st.success("Justificación guardada.")
                            st.rerun()
    else:
        st.error(f"Fuera de rango. Distancia actual: {int(dist)} metros.")
else:
    st.info("Esperando señal GPS...")


# --- 5. PANEL ADMIN ---
st.divider()
with st.expander("🔐 Administración"):
    if st.text_input("Password", type="password", key="p_adm") == "NEOMOTIC2024":
        df_a = conn.read(ttl=0)
        df_a['Hora_dt'] = pd.to_datetime(df_a['Hora'], dayfirst=True, errors='coerce')
        df_h = df_a[df_a['Hora_dt'].dt.date == ahora.date()].copy()
        try: 
            df_empl = conn.read(worksheet="Empleados", ttl=0)
            lista_m = df_empl['Nombre'].tolist()
        except: lista_m = []
        
        t1, t2, t3, t4 = st.tabs(["📋 Hoy", "🚫 Faltantes", "🗺️ Mapa", "🖨️ Generar QR"])
        df_a['Hora_dt'] = pd.to_datetime(df_a['Hora'], dayfirst=True, errors='coerce')
        df_h = df_a[df_a['Hora_dt'].dt.date == ahora.date()].copy()

        with t1: 
            st.dataframe(df_h[['Empleado', 'Hora', 'Tipo', 'Estatus', 'Justificacion']], use_container_width=True)
            if st.button("📧 Enviar Reporte Semanal"):
              with st.spinner("Enviando..."):
                 try:
            # Intentamos ejecutar la función
                     resultado = enviar_reporte_semanal(df_a)
                     if resultado is True: 
                       st.success("✅ Enviado.")
                     else: 
                       st.error("Error al enviar.")
                 except Exception as e:
            # Esto imprimirá el error REAL en tu pantalla de Streamlit
                     st.error(f"Fallo crítico: {e}")

        with t2:
            if lista_m:
                llegaron = df_h[df_h['Tipo'] == 'Entrada']['Empleado'].unique()
                faltan = [e for e in lista_m if e not in llegaron]
                for f in (faltan if faltan else ["¡Completos!"]): st.write(f"❌ {f}" if f != "¡Completos!" else f)
        with t3:
            pts = df_h.dropna(subset=['Lat', 'Lon']).copy()
            if not pts.empty:
                pts = pts.rename(columns={'Lat': 'lat', 'Lon': 'lon'})
                st.map(pts)
            else: st.info("Sin coordenadas hoy.")
        with t4:
            st.subheader("Generador de QR Nativo")
            emp_sel = st.selectbox("Selecciona Empleado:", lista_m)
            if emp_sel:
                qr = qrcode.QRCode(version=1, box_size=10, border=4)
                qr.add_data(emp_sel)
                qr.make(fit=True)
                buf = BytesIO()
                qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
                st.image(buf.getvalue(), caption=f"QR de {emp_sel}", width=250)

