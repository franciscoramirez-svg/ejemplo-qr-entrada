import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime, timedelta, date
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
HORA_SALIDA_OFICIAL = "17:00:00" 
UMBRAL_RETARDO_MINUTOS = 15

OFICINA_LAT = 19.245304  
OFICINA_LON = -96.174232 
RADIO_PERMITIDO = 1000   
TELEFONO_ADMIN_WA = "5212296936270" 

# --- 2. FUNCIÓN DE CORREO CON ALERTAS CRÍTICAS Y ORDEN ALFABÉTICO ---
def enviar_reporte_semanal(df):
    try:
        PASSWORD_APP = st.secrets["EMAIL_PASSWORD"]
        REMITENTE = st.secrets["EMAIL_USER"]
        DESTINATARIOS = ["francisco.ramirez@neomotic.com", "rodolfo.fuentes@neomotic.com"]
        hoy = datetime.now(zona_veracruz)
        fecha_ini = (hoy - timedelta(days=7)).date()
        
        try:
            df_maestra = conn.read(worksheet="Empleados", ttl=0)
        except:
            df_maestra = pd.DataFrame(columns=['Nombre', 'Autoriza_Extra'])

        df_temp = df.copy()
        df_temp['Hora_dt'] = pd.to_datetime(df_temp['Hora'], dayfirst=True, errors='coerce')
        df_filtrado = df_temp[df_temp['Hora_dt'].dt.date >= fecha_ini].copy()
        
        if df_filtrado.empty: return "Sin registros para el reporte."

        df_filtrado['Fecha'] = df_filtrado['Hora_dt'].dt.date
        nom = df_filtrado.groupby(['Empleado', 'Fecha']).agg(
            Entrada=('Hora_dt', 'min'), 
            Salida=('Hora_dt', 'max'),
            Registros=('Tipo', 'count'),
            Primer_Tipo=('Tipo', 'first'),
            Min_Retardo=('Min_Retardo', 'sum'), 
            Estatus_Dia=('Estatus', 'first')
        ).reset_index()

        def calcular_jornada_detallada(row):
            total_h, extras, obs = 0.0, 0.0, "OK"
            if row['Registros'] == 1:
                obs = "⚠️ Olvidó marcar SALIDA" if row['Primer_Tipo'] == 'Entrada' else "⚠️ Olvidó marcar ENTRADA"
            elif row['Entrada'] != row['Salida']:
                total_h = round((row['Salida'] - row['Entrada']).total_seconds()/3600, 2)
                h_sal_ofic = datetime.combine(row['Salida'].date(), datetime.strptime(HORA_SALIDA_OFICIAL, "%H:%M:%S").time()).replace(tzinfo=zona_veracruz)
                salida_real = row['Salida'].replace(tzinfo=zona_veracruz)
                
                if salida_real > h_sal_ofic:
                    permiso = df_maestra.loc[df_maestra['Nombre'] == row['Empleado'], 'Autoriza_Extra']
                    autorizado = (permiso.values == "SÍ") if not permiso.empty else False
                    if autorizado:
                        extras = round((salida_real - h_sal_ofic).total_seconds()/3600, 2)
                        obs = "CON HORAS EXTRAS"
                    else:
                        extras = 0.0
                        obs = "⚠️ SALIDA TARDÍA NO AUTORIZADA"
            return pd.Series([total_h, extras, obs])

        nom[['Total_Horas', 'Horas_Extras', 'Observaciones']] = nom.apply(calcular_jornada_detallada, axis=1)

        # --- LÓGICA DE ALERTAS PARA EL CUERPO DEL CORREO ---
        retardos_graves = df_filtrado[df_filtrado['Estatus'] == "RETARDO CRÍTICO"]
        conteo_r = df_filtrado[df_filtrado['Estatus'] == "Retardo"].groupby('Empleado').size()
        reincidentes = conteo_r[conteo_r >= 3]
        salidas_no_auth = df_filtrado[df_filtrado['Estatus'] == "SALIDA NO AUTORIZADA"]

        alerta_html = ""
        if not retardos_graves.empty:
            alerta_html += "<div style='background:#ff0000;padding:12px;color:white;border-radius:5px;'><b>🚨 RETARDOS CRÍTICOS (>30 MIN):</b><ul>"
            for _, r in retardos_graves.iterrows(): alerta_html += f"<li>{r['Empleado']}: {r['Min_Retardo']} min ({r['Hora']})</li>"
            alerta_html += "</ul></div><br>"
        if not reincidentes.empty or not salidas_no_auth.empty:
            alerta_html += "<div style='background:#fff3cd;padding:10px;border-left:5px solid #ffc107;'><b>⚠️ INCIDENCIAS DE SEMANA:</b><ul>"
            for e, c in reincidentes.items(): alerta_html += f"<li>{e}: Acumula {c} retardos normales.</li>"
            for _, s in salidas_no_auth.iterrows(): alerta_html += f"<li>{s['Empleado']}: Salida NO autorizada ({s['Hora']}).</li>"
            alerta_html += "</ul></div>"

        # --- ORDENAR Y PREPARAR CSV ---
        csv_final = nom[['Empleado', 'Fecha', 'Entrada', 'Salida', 'Total_Horas', 'Horas_Extras', 'Min_Retardo', 'Estatus_Dia', 'Observaciones']]
        csv_final = csv_final.sort_values(by=['Empleado', 'Fecha'], ascending=[True, True])

        msg = MIMEMultipart()
        msg['Subject'] = f"📊 Reporte de Nómina NEOMOTIC - {hoy.strftime('%d/%m/%Y')}"
        msg.attach(MIMEText(f"<html><body><h2>Resumen Semanal</h2>{alerta_html}<p>Detalle adjunto en CSV (Ordenado A-Z).</p></body></html>", 'html'))

        csv_name = f"REPORTE_{hoy.strftime('%d_%m_%Y')}.csv"
        csv_data = csv_final.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(csv_data)
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

# --- 4. INTERFAZ Y REGISTRO ---
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
                            diff = (datetime.combine(date.today(), ahora.time()) - datetime.combine(date.today(), h_lim)).total_seconds() / 60
                            min_r = max(0, int(diff))
                            if min_r > 30: est = "RETARDO CRÍTICO"
                            elif min_r > UMBRAL_RETARDO_MINUTOS: est = "Retardo"
                        elif tipo == "Salida":
                            h_sal = datetime.strptime(HORA_SALIDA_OFICIAL, "%H:%M:%S").time()
                            if ahora.time() > h_sal:
                                try:
                                    df_m = conn.read(worksheet="Empleados", ttl=0)
                                    auth = (df_m.loc[df_m['Nombre'] == data, 'Autoriza_Extra'].values == "SÍ")
                                    est = "Salida Autorizada" if auth else "SALIDA NO AUTORIZADA"
                                except: est = "Salida (Sin validar)"
                            else: est = "Salida a Tiempo"

                        nuevo = pd.DataFrame([[data, ahora.strftime("%d/%m/%Y %H:%M:%S"), lat_act, lon_act, tipo, est, min_r]], 
                                             columns=["Empleado", "Hora", "Lat", "Lon", "Tipo", "Estatus", "Min_Retardo"])
                        _ = conn.update(data=pd.concat([df_act, nuevo], ignore_index=True))
                        
                        if est in ["RETARDO CRÍTICO", "SALIDA NO AUTORIZADA"]:
                            st.error(f"🚨 {data}: {est}. Reportarse con admin.")
                        elif est == "Retardo": st.warning(f"⏳ {data}: Retardo de {min_r} min.")
                        else: st.success(f"✅ {tipo} OK: {est}")
                    st.session_state.procesando = False

                st.subheader(f"Empleado: {data}")
                c1, c2 = st.columns(2)
                c1.button("📥 ENTRADA", on_click=registrar, args=("Entrada",), use_container_width=True, key="btn_e")
                c2.button("📤 SALIDA", on_click=registrar, args=("Salida",), use_container_width=True, key="btn_s")
    else: st.error("Fuera de rango.")

# --- 5. PANEL ADMIN ---
# --- 5. PANEL ADMIN (ACTUALIZADO CON VISOR DE QR) ---
st.divider()
with st.expander("🔐 Administración"):
    if st.text_input("Password", type="password", key="p_adm") == "NEOMOTIC2024":
        df_a = conn.read(ttl=0)
        try: 
            df_empleados = conn.read(worksheet="Empleados", ttl=0)
            lista_m = df_empleados['Nombre'].tolist()
        except: 
            lista_m = []
            df_empleados = pd.DataFrame()
        
        # Agregamos la pestaña "Generar QR" al final
        t1, t2, t3, t4 = st.tabs(["📋 Hoy", "🚫 Faltantes", "🗺️ Mapa", "🖨️ Generar QR"])
        
        df_a['Hora_dt'] = pd.to_datetime(df_a['Hora'], dayfirst=True, errors='coerce')
        df_h = df_a[df_a['Hora_dt'].dt.date == ahora.date()]

        with t1: 
            st.dataframe(df_h[['Empleado', 'Hora', 'Tipo', 'Estatus']], use_container_width=True)
            if st.button("📧 Enviar Reporte Semanal Completo", key="btn_mail_final"):
                with st.spinner("Procesando y validando permisos..."):
                    res = enviar_reporte_semanal(df_a)
                    if res is True: st.success("✅ Reporte enviado con éxito.")
                    else: st.error(f"Error: {res}")
        
        with t2:
            if lista_m:
                llegaron = df_h[df_h['Tipo'] == 'Entrada']['Empleado'].unique()
                faltan = [e for e in lista_m if e not in llegaron]
                if faltan:
                    for f in faltan: st.write(f"❌ {f}")
                else: st.success("¡Todos los empleados registraron entrada!")
        
        with t3:
            pts = df_h.dropna(subset=['Lat', 'Lon']).rename(columns={'Lat':'lat', 'Lon':'lon'})
            st.map(pts if not pts.empty else pd.DataFrame({'lat':[OFICINA_LAT],'lon':[OFICINA_LON]}))

        # --- NUEVA PESTAÑA: GENERADOR DE QR DIGITAL ---
                # --- PESTAÑA DE GENERACIÓN DE QR (ACTUALIZADA) ---
        with t4:
            st.subheader("Generador de QR Digital")
            if lista_m:
                emp_sel = st.selectbox("Selecciona Empleado:", lista_m)
                if emp_sel:
                    # Usamos QuickChart API (Alternativa moderna a Google Charts)
                    nombre_encoded = urllib.parse.quote(emp_sel)
                    # Nueva URL funcional:
                    qr_url = f"https://quickchart.io{nombre_encoded}&size=300"
                    
                    st.image(qr_url, caption=f"QR oficial de {emp_sel}", width=250)
                    st.info("💡 Este código es generado mediante QuickChart y es 100% compatible.")
