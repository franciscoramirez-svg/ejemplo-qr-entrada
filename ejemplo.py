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
        # 1. Validación inicial de secretos
        try:
            PASSWORD_APP = st.secrets["EMAIL_PASSWORD"]
            REMITENTE = st.secrets["EMAIL_USER"]
            DESTINATARIOS = ["francisco.ramirez@neomotic.com", "rodolfo.fuentes@neomotic.com"]
        except KeyError:
            return "¡Faltan los secretos en la configuración!"

        # 2. TODO ESTO DEBE ESTAR INDENTADO (DENTRO DEL TRY PRINCIPAL)
        hoy = datetime.now(zona_veracruz)
        
        df_temp = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df_temp['Hora']):
             df_temp['Hora_dt'] = pd.to_datetime(df_temp['Hora'], dayfirst=True, errors='coerce')
        else:
             df_temp['Hora_dt'] = df_temp['Hora']

        resumen = df_temp.groupby(['Empleado', 'Tipo']).size().unstack(fill_value=0)
        
        msg = MIMEMultipart()
        msg['From'] = REMITENTE
        msg['To'] = "francisco.ramirez@neomotic.com, rodolfo.fuentes@neomotic.com".join(DESTINATARIOS)
        msg['Subject'] = f"📊 Reporte de Asistencia NEOMOTIC - {hoy.strftime('%d/%m/%Y')}"
        
        cuerpo = f"Hola,\n\nSe adjunta el resumen de asistencias solicitado:\n\n{resumen.to_string()}\n\nGenerado por Sistema NEOMOTIC."
        msg.attach(MIMEText(cuerpo, 'plain'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(REMITENTE, PASSWORD_APP)
        server.send_message(msg)
        server.quit()
        
        return True # Ahora sí devolverá True al finalizar con éxito

    except Exception as e:
        return f"Error inesperado: {str(e)}"

def calcular_distancia(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
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
                
                if st.session_state.ultimo_registro:
                    reg = st.session_state.ultimo_registro
                    resumen_texto = f"Registro Neomotic: {reg['empleado']} - {reg['tipo'].upper()} - {reg['hora']}"
                    texto_url = urllib.parse.quote(resumen_texto)
                    url_directa = f"whatsapp://send?phone={TELEFONO_ADMIN_WA}&text={texto_url}"
                    url_web = f"https://web.whatsapp.com{TELEFONO_ADMIN_WA}&text={texto_url}"
                    
                    st.divider()
                    st.info("Confirmar por WhatsApp:")
                    c_wa1, c_wa2 = st.columns(2)
                    with c_wa1:
                        st.link_button("📱 En Celular", url_directa, use_container_width=True)
                    with c_wa2:
                        st.link_button("💻 En PC", url_web, use_container_width=True)
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
                
                # --- PRUEBA DE CORREO ---
                st.divider()
                st.subheader("📧 Prueba de Sistema de Correo")
                if st.button("Mandar Reporte de HOY por Correo"):
                    with st.spinner("Enviando..."):
                        resultado_envio = enviar_reporte_semanal(df_dia)
                        if resultado_envio is True:
                            st.success("¡Correo enviado! Revisa francisco.ramirez@neomotic.com")
                        else:
                            st.error(f"Error: {resultado_envio}")
            else:
                st.info("Sin registros hoy.")










