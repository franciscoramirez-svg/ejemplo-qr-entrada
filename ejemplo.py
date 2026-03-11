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
import urllib.parse  # Necesario para WhatsApp
import requests
from email.mime.image import MIMEImage

# --- 1. CONFIGURACIÓN INICIAL ---
zona_veracruz = pytz.timezone('America/Mexico_City')
conn = st.connection("gsheets", type=GSheetsConnection)

# ---------------------------------------------
HORA_ENTRADA_OFICIAL = "07:00:00" 
UMBRAL_RETARDO_MINUTOS = 15
# ----------------------------------------------

OFICINA_LAT = 19.245304  
OFICINA_LON = -96.174232 
RADIO_PERMITIDO = 1000   
TELEFONO_ADMIN_WA = "5212296936270" 


#--------------------------------------------
def enviar_reporte_semanal(df):
    try:
        PASSWORD_APP = st.secrets["EMAIL_PASSWORD"]
        REMITENTE = st.secrets["EMAIL_USER"]
        DESTINATARIOS = ["francisco.ramirez@neomotic.com", "rodolfo.fuentes@neomotic.com"]
        
        hoy = datetime.now(zona_veracruz)
        fecha_inicio = (hoy - timedelta(days=7)).date()
        
        df_temp = df.copy()
        df_temp['Hora_dt'] = pd.to_datetime(df_temp['Hora'], dayfirst=True, errors='coerce')
        df_filtrado = df_temp[df_temp['Hora_dt'].dt.date >= fecha_inicio].copy()
        
        if df_filtrado.empty: return "Sin registros."

        # --- LÓGICA DE ALERTAS: CONTAR RETARDOS ---
        # Filtramos solo las entradas que fueron marcadas como "Retardo"
        conteo_retardos = df_filtrado[df_filtrado['Estatus'] == "Retardo"].groupby('Empleado').size()
        
        # --- PREPARAR RESUMEN HTML CON COLORES ---
        resumen = df_filtrado.groupby(['Empleado', 'Tipo']).size().unstack(fill_value=0)
        
        # Creamos la tabla HTML manualmente para meter el estilo
        filas_html = ""
        for emp, row in resumen.iterrows():
            num_retardos = conteo_retardos.get(emp, 0)
            # Si tiene más de 3 retardos, ponemos el fondo de la fila en rojo claro
            estilo_fila = 'style="background-color: #ffcccc;"' if num_retardos >= 3 else ""
            alerta_txt = f" <br><span style='color:red; font-size:10px;'>⚠️ {num_retardos} Retardos</span>" if num_retardos >= 3 else ""
            
            filas_html += f"""
            <tr {estilo_fila}>
                <td style="padding: 8px; border: 1px solid #ddd;">{emp}{alerta_txt}</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align:center;">{row.get('Entrada', 0)}</td>
                <td style="padding: 8px; border: 1px solid #ddd; text-align:center;">{row.get('Salida', 0)}</td>
            </tr>
            """

        msg = MIMEMultipart("alternative")
        msg['From'], msg['To'] = REMITENTE, ", ".join(DESTINATARIOS)
        msg['Subject'] = f"⚠️ REPORTE CRÍTICO ASISTENCIA - {hoy.strftime('%d/%m/%Y')}"

        html_cuerpo = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <div style="max-width: 600px; border: 2px solid #004a99; padding: 20px;">
                <h2 style="color: #004a99;">Resumen Semanal de Asistencia</h2>
                <p>Periodo: <b>{fecha_inicio.strftime('%d/%m/%Y')}</b> al <b>{hoy.strftime('%d/%m/%Y')}</b></p>
                
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="background-color: #004a99; color: white;">
                            <th style="padding: 10px; border: 1px solid #ddd;">Empleado</th>
                            <th style="padding: 10px; border: 1px solid #ddd;">Entradas</th>
                            <th style="padding: 10px; border: 1px solid #ddd;">Salidas</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filas_html}
                    </tbody>
                </table>
                
                <p style="margin-top: 20px; font-size: 12px; color: #666;">
                    * Las filas en <span style="color:red; font-weight:bold;">ROJO</span> indican empleados con 3 o más retardos en la semana.
                </p>
            </div>
        </body>
        </html>
        """
        msg.attach(MIMEText(html_cuerpo, 'html'))

        # ADJUNTO: Reporte de Nómina con Minutos
        # (Aquí usamos la lógica de la Parte 2 que ya calculaba horas)
        df_filtrado['Fecha'] = df_filtrado['Hora_dt'].dt.date
        nomina = df_filtrado.groupby(['Empleado', 'Fecha']).agg(
            Entrada=('Hora_dt', 'min'),
            Salida=('Hora_dt', 'max'),
            Minutos_Retardo=('Min_Retardo', 'sum')
        ).reset_index()
        
        csv_binario = nomina.to_csv(index=False).encode('utf-8')
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(csv_binario)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="Reporte_Nomina_TRV.csv"')
        msg.attach(part)

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(REMITENTE, PASSWORD_APP)
            server.sendmail(REMITENTE, DESTINATARIOS, msg.as_string())
        return True 

    except Exception as e:
        return f"Error en reporte: {str(e)}"



# --------------------

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

st.title("📍 Registro de Asistencia del personal en TRV")

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

                                # --- BUSCA ESTA PARTE EN TU CÓDIGO Y REEMPLÁZALA ---
                def registrar(tipo):
                    # Todo este bloque debe tener 4 espacios de sangría hacia la derecha
                    st.session_state.procesando = True
                    ya_existe = not df_actual[(df_actual['Empleado'] == data) & 
                                            (df_actual['Hora'].str.contains(fecha_hoy)) & 
                                            (df_actual['Tipo'] == tipo)].empty
                    if ya_existe:
                        st.warning(f"Ya existe un registro de {tipo} para hoy.")
                    else:
                        estatus = "A Tiempo"
                        minutos_retardo = 0
                        if tipo == "Entrada":
                            h_limite = datetime.strptime(HORA_ENTRADA_OFICIAL, "%H:%M:%S").time()
                            dt_actual = datetime.combine(ahora.date(), ahora.time())
                            dt_limite = datetime.combine(ahora.date(), h_limite)
                            diff = dt_actual - dt_limite
                            minutos_retardo = max(0, int(diff.total_seconds() / 60))
                            if minutos_retardo > UMBRAL_RETARDO_MINUTOS:
                                estatus = "Retardo"

                        nuevo = pd.DataFrame([[data, hora_str, lat_actual, lon_actual, tipo, estatus, minutos_retardo]], 
                                             columns=["Empleado", "Hora", "Lat", "Lon", "Tipo", "Estatus", "Min_Retardo"])
                        
                        df_final = pd.concat([df_actual, nuevo], ignore_index=True)
                        conn.update(data=df_final)
                        
                        st.session_state.ultimo_registro = {"empleado": data, "tipo": tipo, "hora": hora_str}
                        st.toast(f"¡{tipo} registrada!", icon="🚀")
                        if tipo == "Entrada": st.balloons() 
                        else: st.snow()
                    st.session_state.procesando = False

                # Los botones de abajo NO van dentro de la función (van alineados con 'def')
                with col1:
                    st.button("📥 ENTRADA", on_click=registrar, args=("Entrada",), use_container_width=True)
                with col2:
                    st.button("📤 SALIDA", on_click=registrar, args=("Salida",), use_container_width=True)


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
                            st.success("¡Correo enviado! Revisa tu bandeja")
                        else:
                            st.error(f"Error: {resultado_envio}")
            else:
                st.info("Sin registros hoy.")
