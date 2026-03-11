import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime, timedelta
from streamlit_js_eval import get_geolocation
import cv2
import numpy as np
from math import radians, cos, sin, asin, sqrt
import pytz
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import urllib.parse

# --- 1. CONFIGURACIÓN INICIAL ---
zona_veracruz = pytz.timezone('America/Mexico_City')
conn = st.connection("gsheets", type=GSheetsConnection)

HORA_ENTRADA_OFICIAL = "07:00:00" 
UMBRAL_RETARDO_MINUTOS = 15
OFICINA_LAT = 19.245304  
OFICINA_LON = -96.174232 
RADIO_PERMITIDO = 1000   
TELEFONO_ADMIN_WA = "5212296936270" 

# --- 2. FUNCIÓN DE CORREO (LIMPIA) ---
def enviar_reporte_semanal(df):
    try:
        PASSWORD_APP = st.secrets["EMAIL_PASSWORD"]
        REMITENTE = st.secrets["EMAIL_USER"]
        DESTINATARIOS = ["francisco.ramirez@neomotic.com", "rodolfo.fuentes@neomotic.com"]
        hoy = datetime.now(zona_veracruz)
        fecha_ini = (hoy - timedelta(days=7)).date()
        
        df_temp = df.copy()
        df_temp['Hora_dt'] = pd.to_datetime(df_temp['Hora'], dayfirst=True, errors='coerce')
        df_filtrado = df_temp[df_temp['Hora_dt'].dt.date >= fecha_ini].copy()
        
        if df_filtrado.empty: return "Sin registros."

        
               # --- MEJORA VISUAL: LISTA DE RETARDOS EN EL CORREO ---
        conteo = df_filtrado[df_filtrado['Estatus'] == "Retardo"].groupby('Empleado').size()
        criticos = conteo[conteo >= 3]
        
        if not criticos.empty:
            alerta_html = """
            <div style="background-color: #fff0f0; border-left: 5px solid #ff4b4b; padding: 15px; margin: 10px 0;">
                <p style='color:#d33; font-weight:bold; margin-top:0;'>⚠️ ALERTAS DE RETARDOS CRÍTICOS (3+):</p>
                <ul style="list-style-type: none; padding-left: 0;">
            """
            for e, c in criticos.items():
                alerta_html += f"<li style='padding: 5px 0; border-bottom: 1px solid #ffebeb;'>❌ <b>{e}</b>: {c} retardos acumulados.</li>"
            alerta_html += "</ul></div>"
        else:
            alerta_html = """
            <div style="background-color: #f0fff0; border-left: 5px solid #28a745; padding: 15px; margin: 10px 0;">
                <p style='color:#1e7e34; font-weight:bold; margin:0;'>✅ Personal con asistencia regular. No hay alertas críticas.</p>
            </div>
            """
            
        msg = MIMEMultipart()
        msg['Subject'] = f"📊 Reporte de Asistencia NEOMOTIC - {hoy.strftime('%d/%m/%Y')}"
        msg.attach(MIMEText(f"<html><body><h2>Reporte Semanal TRV</h2>{alerta_html}<p>Detalle en adjunto.</p></body></html>", 'html'))

        # CSV Adjunto con nombre dinámico
        df_filtrado['Fecha'] = df_filtrado['Hora_dt'].dt.date
        nom = df_filtrado.groupby(['Empleado', 'Fecha']).agg(Entrada=('Hora_dt', 'min'), Salida=('Hora_dt', 'max'), Min_Retardo=('Min_Retardo', 'sum'), Estatus_Dia=('Estatus', 'first')).reset_index()
        nom['Total_Horas'] = nom.apply(lambda r: round((r['Salida'] - r['Entrada']).total_seconds()/3600, 2) if r['Entrada'] != r['Salida'] else 0.0, axis=1)
        nom['Entrada'], nom['Salida'] = nom['Entrada'].dt.strftime('%H:%M:%S'), nom['Salida'].dt.strftime('%H:%M:%S')
        
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(nom.to_csv(index=False).encode('utf-8'))
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="REPORTE_ASISTENCIA_TRV_{hoy.strftime("%d_%m_%Y")}.csv"')
        msg.attach(part)

        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(REMITENTE, PASSWORD_APP)
            s.sendmail(REMITENTE, DESTINATARIOS, msg.as_string())
        return True
    except Exception as e: return str(e)

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
        foto = st.camera_input("Escanea QR")
        if foto and not st.session_state.procesando:
            img = cv2.imdecode(np.asarray(bytearray(foto.getvalue()), dtype=np.uint8), 1)
            data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
            if data:
                df_act = conn.read(ttl=0)
                def registrar(tipo):
                    st.session_state.procesando = True
                    # MEJORA 2: Validar salida olvidada
                    ult_reg = df_act[df_act['Empleado'] == data].tail(1)
                    if tipo == "Entrada" and not ult_reg.empty and ult_reg['Tipo'].values[0] == "Entrada":
                        st.error(f"⚠️ {data}, no marcaste SALIDA anterior. Avisa a tu jefe.")
                    else:
                        est, min_r = "A Tiempo", 0
                        if tipo == "Entrada":
                            diff = datetime.combine(ahora.date(), ahora.time()) - datetime.combine(ahora.date(), datetime.strptime(HORA_ENTRADA_OFICIAL, "%H:%M:%S").time())
                            min_r = max(0, int(diff.total_seconds() / 60))
                            if min_r > UMBRAL_RETARDO_MINUTOS: est = "Retardo"
                        nuevo = pd.DataFrame([[data, ahora.strftime("%d/%m/%Y %H:%M:%S"), lat_act, lon_act, tipo, est, min_r]], columns=["Empleado", "Hora", "Lat", "Lon", "Tipo", "Estatus", "Min_Retardo"])
                        conn.update(data=pd.concat([df_act, nuevo], ignore_index=True))
                        st.balloons() if tipo == "Entrada" else st.snow()
                    st.session_state.procesando = False

                st.subheader(f"Empleado: {data}")
                c1, c2 = st.columns(2)
                c1.button("📥 ENTRADA", on_click=registrar, args=("Entrada",), use_container_width=True, key="btn_e")
                c2.button("📤 SALIDA", on_click=registrar, args=("Salida",), use_container_width=True, key="btn_s")
    else: st.error("Fuera de rango.")

# --- 4. PANEL ADMIN (MEJORAS 3 Y 4) ---
st.divider()
with st.expander("🔐 Administración"):
    if st.text_input("Password", type="password", key="p_adm") == "NEOMOTIC2024":
        df_a = conn.read(ttl=0)
        try:
            lista_m = conn.read(worksheet="Empleados", ttl=0)['Nombre'].tolist()
        except: lista_m = []
        
        t1, t2, t3 = st.tabs(["📋 Hoy", "🚫 Faltantes", "🗺️ Mapa"])
        df_a['Hora_dt'] = pd.to_datetime(df_a['Hora'], dayfirst=True, errors='coerce')
        df_h = df_a[df_a['Hora_dt'].dt.date == ahora.date()]

        with t1: 
            st.dataframe(df_h[['Empleado', 'Hora', 'Tipo', 'Estatus']], use_container_width=True)
            if st.button("📧 Enviar Reporte de Hoy"): enviar_reporte_semanal(df_h)
        with t2:
            if lista_m:
                llegaron = df_h[df_h['Tipo'] == 'Entrada']['Empleado'].unique()
                faltan = [e for e in lista_m if e not in llegaron]
                
                if faltan:
                    st.error(f"⚠️ Faltan {len(faltan)} personas por registrar entrada:")
                    # Mostramos la lista de nombres uno por uno para que sea más legible
                    for persona in faltan:
                        st.write(f"❌ {persona}")
                else:
                    st.success("✅ ¡Personal completo! Todos han registrado su entrada hoy.")
            else:
                st.info("ℹ️ No hay nombres en la pestaña 'Empleados' de tu Google Sheet.")

        with t3:
            pts = df_h.dropna(subset=['Lat', 'Lon']).rename(columns={'Lat':'lat', 'Lon':'lon'})
            st.map(pts if not pts.empty else pd.DataFrame({'lat':[OFICINA_LAT],'lon':[OFICINA_LON]}))


