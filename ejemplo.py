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
import urllib.parse  # Necesario para WhatsApp

# --- 1. CONFIGURACIÓN INICIAL ---
zona_veracruz = pytz.timezone('America/Mexico_City')
conn = st.connection("gsheets", type=GSheetsConnection)

OFICINA_LAT = 19.245304  
OFICINA_LON = -96.174232 
RADIO_PERMITIDO = 1000   
TELEFONO_ADMIN_WA = "5212296936270" 

# --- FUNCIÓN: ENVIAR REPORTE POR EMAIL ---
def enviar_reporte_semanal(df):
    try:
        REMITENTE = st.secrets["EMAIL_USER"]
        DESTINATARIO = "francisco.ramirez@neomotic.com"
        PASSWORD_APP = st.secrets["EMAIL_PASS"]

        hoy = datetime.now(zona_veracruz)
        hace_7_dias = hoy - timedelta(days=7)
        df['Hora_dt'] = pd.to_datetime(df['Hora'], dayfirst=True, errors='coerce')
        df_semana = df[df['Hora_dt'] >= hace_7_dias].copy()
        
        if df_semana.empty:
            return "No hay datos para enviar esta semana."

        resumen = df_semana.groupby(['Empleado', 'Tipo']).size().unstack(fill_value=0)
        msg = MIMEMultipart()
        msg['From'] = REMITENTE
        msg['To'] = DESTINATARIO
        msg['Subject'] = f"📊 Reporte Semanal NEOMOTIC ({hace_7_dias.strftime('%d/%m')} al {hoy.strftime('%d/%m')})"
        
        cuerpo = f"Hola,\n\nResumen de asistencias:\n\n{resumen.to_string()}\n\nGenerado por Sistema NEOMOTIC."
        msg.attach(MIMEText(cuerpo, 'plain'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(REMITENTE, PASSWORD_APP)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        return str(e)

def calcular_distancia(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    dlat = dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return c * 6371000 

st.set_page_config(page_title="NEOMOTIC Access", page_icon="📍")

# --- 2. LOGICA DE REPORTE JUEVES ---
ahora = datetime.now(zona_veracruz)
if ahora.strftime('%A') == 'Thursday':
    with st.sidebar:
        st.warning("📅 ¡Hoy es jueves de reporte!")
        if st.button("📧 Enviar Reporte Semanal al Jefe"):
            df_para_correo = conn.read(ttl=0)
            resultado = enviar_reporte_semanal(df_para_correo)
            if resultado is True:
                st.success("Reporte enviado con éxito.")
            else:
                st.error(f"Error: {resultado}")

st.title("📍 Registro de Asistencia Pro")

# --- 3. GESTIÓN DE ESTADO Y REGISTRO ---
if 'procesando' not in st.session_state:
    st.session_state.procesando = False
if 'ultimo_registro' not in st.session_state:
    st.session_state.ultimo_registro = None

loc = get_geolocation()

if loc:
    lat_actual = loc['coords']['latitude']
    lon_actual = loc['coords']['longitude']
    accuracy = loc['coords'].get('accuracy', 0)
    distancia = calcular_distancia(lat_actual, lon_actual, OFICINA_LAT, OFICINA_LON)
    
    if distancia <= RADIO_PERMITIDO:
        st.success(f"✅ Zona confirmada (Precisión: {int(accuracy)}m)")
        foto = st.camera_input("Escanea tu QR")
        
        if foto and not st.session_state.procesando:
            file_bytes = np.asarray(bytearray(foto.getvalue()), dtype=np.uint8)
            img = cv2.imdecode(file_bytes, 1)
            data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)

            if data:
                df_actual = conn.read(ttl=0)
                fecha_hoy = ahora.strftime("%d/%m/%Y")
                hora_str = ahora.strftime("%d/%m/%Y %H:%M:%S")

                st.subheader(f"Empleado: {data}")
                col1, col2 = st.columns(2)

                def registrar(tipo):
                    st.session_state.procesando = True
                    ya_existe = not df_actual[(df_actual['Empleado'] == data) & 
                                            (df_actual['Hora'].str.contains(fecha_hoy)) & 
                                            (df_actual['Tipo'] == tipo)].empty
                    if ya_existe:
                        st.warning(f"Ya existe un registro de {tipo} para hoy.")
                    else:
                        nuevo = pd.DataFrame([[data, hora_str, lat_actual, lon_actual, tipo]], 
                                             columns=["Empleado", "Hora", "Lat", "Lon", "Tipo"])
                        df_final = pd.concat([df_actual, nuevo], ignore_index=True)
                        conn.update(data=df_final)
                        st.session_state.ultimo_registro = {"empleado": data, "tipo": tipo, "hora": hora_str}
                        st.toast(f"¡{tipo} registrada!", icon="🚀")
                        if tipo == "Entrada": st.balloons() 
                        else: st.snow()
                    st.session_state.procesando = False

                with col1:
                    st.button("📥 ENTRADA", on_click=registrar, args=("Entrada",), use_container_width=True)
                with col2:
                    st.button("📤 SALIDA", on_click=registrar, args=("Salida",), use_container_width=True)
                
                # --- BOTÓN DE WHATSAPP: SOLUCIÓN FINAL (HTML DIRECTO) ---
                if st.session_state.ultimo_registro:
                    reg = st.session_state.ultimo_registro
                    resumen_texto = f"Registro Neomotic: {reg['empleado']} - {reg['tipo'].upper()} - {reg['hora']}"
                    texto_url = urllib.parse.quote(resumen_texto)
                    
                    # URL wa.me corregida con el slash y signo de interrogación adecuado
                    url_wa = f"https://wa.me{TELEFONO_ADMIN_WA}?text={texto_url}"
                    
                    st.markdown("---")
                    # Botón diseñado con HTML para evitar bloqueos de pop-up
                    st.markdown(f"""
                        <a href="{url_wa}" target="_blank" style="text-decoration: none;">
                            <div style="
                                background-color: #25D366;
                                color: white;
                                padding: 12px 24px;
                                text-align: center;
                                border-radius: 8px;
                                font-weight: bold;
                                font-size: 16px;
                                border: none;
                                display: block;
                                cursor: pointer;
                            ">
                                📲 CONFIRMAR POR WHATSAPP
                            </div>
                        </a>
                    """, unsafe_allow_html=True)

            else:
                st.error("QR no legible.")
    else:
        st.error(f"Fuera de rango ({int(distancia)}m).")
else:
    st.info("Obteniendo ubicación...")

# --- 4. PANEL ADMIN ---
st.divider()
with st.expander("🔐 Panel de Administración"):
    if st.text_input("Contraseña", type="password") == "NEOMOTIC2024":
        df_admin = conn.read(ttl=0)
        if not df_admin.empty:
            df_admin['Hora_dt'] = pd.to_datetime(df_admin['Hora'], dayfirst=True, errors='coerce')
            fecha_sel = st.date_input("Consultar día:", ahora)
            df_dia = df_admin[df_admin['Hora_dt'].dt.date == fecha_sel]
            
            if not df_dia.empty:
                resumen_lista = []
                for emp in df_dia['Empleado'].unique():
                    d_emp = df_dia[df_dia['Empleado'] == emp]
                    ent = d_emp[d_emp['Tipo'] == 'Entrada']['Hora_dt'].min()
                    sal = d_emp[d_emp['Tipo'] == 'Salida']['Hora_dt'].max()
                    horas = (sal - ent).total_seconds()/3600 if pd.notnull(sal) and pd.notnull(ent) else 0
                    resumen_lista.append({"Empleado": emp, "Entrada": ent, "Salida": sal, "Horas": round(horas, 2)})
                
                st.table(pd.DataFrame(resumen_lista))
                csv = df_dia.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Descargar Reporte CSV", csv, f"reporte_{fecha_sel}.csv", "text/csv")
