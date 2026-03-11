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

# Horarios Oficiales NEOMOTIC
HORA_ENTRADA_OFICIAL = "07:00:00" 
HORA_SALIDA_OFICIAL = "17:00:00" # 5:00 PM
UMBRAL_RETARDO_MINUTOS = 15

OFICINA_LAT = 19.245304  
OFICINA_LON = -96.174232 
RADIO_PERMITIDO = 1000   
TELEFONO_ADMIN_WA = "5212296936270" 

# --- 2. FUNCIÓN DE CORREO CON HORAS EXTRAS ---
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

        df_filtrado['Fecha'] = df_filtrado['Hora_dt'].dt.date
        
        # Agrupamos datos para identificar entradas y salidas
        nom = df_filtrado.groupby(['Empleado', 'Fecha']).agg(
            Entrada=('Hora_dt', 'min'), 
            Salida=('Hora_dt', 'max'),
            Registros=('Tipo', 'count'), # Contamos cuántas veces marcó
            Primer_Tipo=('Tipo', 'first'),
            Ultimo_Tipo=('Tipo', 'last'),
            Min_Retardo=('Min_Retardo', 'sum'), 
            Estatus_Dia=('Estatus', 'first')
        ).reset_index()

        def calcular_jornada_detallada(row):
            total_h = 0.0
            extras = 0.0
            obs = "OK"
            
            # Caso 1: Solo marcó una vez (Olvidó el otro registro)
            if row['Registros'] == 1:
                if row['Primer_Tipo'] == 'Entrada':
                    obs = "⚠️ Olvidó marcar SALIDA"
                else:
                    obs = "⚠️ Olvidó marcar ENTRADA"
            
            # Caso 2: Marcó Entrada y Salida (Registro completo)
            elif row['Entrada'] != row['Salida']:
                total_h = round((row['Salida'] - row['Entrada']).total_seconds()/3600, 2)
                
                # Horas Extras (Después de las 5:00 PM)
                h_sal_ofic = datetime.combine(row['Salida'].date(), datetime.strptime(HORA_SALIDA_OFICIAL, "%H:%M:%S").time()).replace(tzinfo=zona_veracruz)
                salida_real = row['Salida'].replace(tzinfo=zona_veracruz)
                
                if salida_real > h_sal_ofic:
                    extras = round((salida_real - h_sal_ofic).total_seconds()/3600, 2)
                    obs = "CON HORAS EXTRAS"
            
            return pd.Series([total_h, extras, obs])

        # Aplicamos la nueva lógica
        nom[['Total_Horas', 'Horas_Extras', 'Observaciones']] = nom.apply(calcular_jornada_detallada, axis=1)

        # --- PREPARAR CORREO ---
        conteo_retardos = df_filtrado[df_filtrado['Estatus'] == "Retardo"].groupby('Empleado').size()
        criticos = conteo_retardos[conteo_retardos >= 3]
        
        # Resumen de incidencias (olvidos) para el cuerpo del correo
        olvidos = nom[nom['Observaciones'].str.contains("⚠️")]
        
        alerta_html = ""
        if not criticos.empty:
            alerta_html += "<div style='background:#fff0f0;padding:10px;border-left:5px solid red;'><b>⚠️ RETARDOS CRÍTICOS:</b><ul>"
            for e, c in criticos.items(): alerta_html += f"<li>{e}: {c} retardos</li>"
            alerta_html += "</ul></div><br>"
            
        if not olvidos.empty:
            alerta_html += "<div style='background:#fff3cd;padding:10px;border-left:5px solid #ffc107;'><b>🔔 REGISTROS INCOMPLETOS:</b><ul>"
            for _, r in olvidos.iterrows(): alerta_html += f"<li>{r['Empleado']} ({r['Fecha']}): {r['Observaciones']}</li>"
            alerta_html += "</ul></div>"

        msg = MIMEMultipart()
        msg['Subject'] = f"📊 Reporte Nómina y Observaciones - {hoy.strftime('%d/%m/%Y')}"
        msg.attach(MIMEText(f"<html><body><h2>Resumen Semanal NEOMOTIC</h2>{alerta_html}<br><p>El CSV adjunto contiene el desglose de Horas Extras y Observaciones.</p></body></html>", 'html'))

        # Adjunto CSV
        csv_name = f"REPORTE_ASISTENCIA_TRV_{hoy.strftime('%d_%m_%Y')}.csv"
        # Limpiamos columnas temporales antes de exportar
        csv_data = nom[['Empleado', 'Fecha', 'Entrada', 'Salida', 'Total_Horas', 'Horas_Extras', 'Min_Retardo', 'Estatus_Dia', 'Observaciones']]
        
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(csv_data.to_csv(index=False).encode('utf-8'))
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{csv_name}"')
        msg.attach(part)

        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(REMITENTE, PASSWORD_APP)
            s.sendmail(REMITENTE, DESTINATARIOS, msg.as_string())
        return True
    except Exception as e: return str(e)


# --- 3. LÓGICA DE DISTANCIA ---
def calcular_distancia(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    a = sin((lat2-lat1)/2)**2 + cos(lat1) * cos(lat2) * sin((lon2-lon1)/2)**2
    return (2 * asin(sqrt(a))) * 6371000 

# --- 4. INTERFAZ ---
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
                    ult_reg = df_act[df_act['Empleado'] == data].tail(1)
                    if tipo == "Entrada" and not ult_reg.empty and ult_reg['Tipo'].values == "Entrada":
                        st.error(f"⚠️ {data}, no marcaste SALIDA anterior.")
                    else:
                        est, min_r = "A Tiempo", 0
                        if tipo == "Entrada":
                            h_lim = datetime.strptime(HORA_ENTRADA_OFICIAL, "%H:%M:%S").time()
                            diff = datetime.combine(ahora.date(), ahora.time()) - datetime.combine(ahora.date(), h_lim)
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

# --- 5. PANEL ADMIN ---
st.divider()
with st.expander("🔐 Administración"):
    if st.text_input("Password", type="password", key="p_adm") == "NEOMOTIC2024":
        df_a = conn.read(ttl=0)
        try: lista_m = conn.read(worksheet="Empleados", ttl=0)['Nombre'].tolist()
        except: lista_m = []
        
        t1, t2, t3 = st.tabs(["📋 Hoy", "🚫 Faltantes", "🗺️ Mapa"])
        df_a['Hora_dt'] = pd.to_datetime(df_a['Hora'], dayfirst=True, errors='coerce')
        df_h = df_a[df_a['Hora_dt'].dt.date == ahora.date()]

        with t1: 
            st.dataframe(df_h[['Empleado', 'Hora', 'Tipo', 'Estatus']], use_container_width=True)
            if st.button("📧 Enviar Reporte de Prueba Hoy", key="btn_mail"):
                with st.spinner("Enviando..."):
                    res = enviar_reporte_semanal(df_h)
                    if res is True: st.success("✅ Enviado")
                    else: st.error(res)
        with t2:
            if lista_m:
                llegaron = df_h[df_h['Tipo'] == 'Entrada']['Empleado'].unique()
                faltan = [e for e in lista_m if e not in llegaron]
                if faltan:
                    for f in faltan: st.write(f"❌ {f}")
                else: st.success("¡Completos!")
        with t3:
            pts = df_h.dropna(subset=['Lat', 'Lon']).rename(columns={'Lat':'lat', 'Lon':'lon'})
            st.map(pts if not pts.empty else pd.DataFrame({'lat':[OFICINA_LAT],'lon':[OFICINA_LON]}))
            

