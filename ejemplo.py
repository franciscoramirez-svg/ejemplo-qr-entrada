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
import qrcode
from io import BytesIO

# --- 1. CONFIGURACIÓN INICIAL ---
zona_veracruz = pytz.timezone('America/Mexico_City')
conn = st.connection("gsheets", type=GSheetsConnection)

HORA_ENTRADA_OFICIAL = "07:00:00" 
HORA_SALIDA_OFICIAL = "17:00:00" 
UMBRAL_RETARDO_MINUTOS = 15

OFICINA_LAT = 19.245304  
OFICINA_LON = -96.174232 
RADIO_PERMITIDO = 1000   

# --- 2. FUNCIÓN DE CORREO CON DISEÑO Y JUSTIFICACIÓN ---
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
            Estatus_Dia=('Estatus', 'first'),
            Justificacion=('Justificacion', 'first')
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
                    tiene_just = pd.notna(row['Justificacion']) and str(row['Justificacion']).strip() != ""

                    if autorizado or tiene_just:
                        extras = round((salida_real - h_sal_ofic).total_seconds()/3600, 2)
                        obs = f"CON HORAS EXTRAS (Justificado: {row['Justificacion']})" if tiene_just else "CON HORAS EXTRAS"
                    else:
                        extras = 0.0
                        obs = "⚠️ SALIDA TARDÍA NO AUTORIZADA"
            return pd.Series([total_h, extras, obs])

        nom[['Total_Horas', 'Horas_Extras', 'Observaciones']] = nom.apply(calcular_jornada_detallada, axis=1)

        # Diseño del correo (Semáforo de incidencias)
        retardos_graves = df_filtrado[df_filtrado['Estatus'] == "RETARDO CRÍTICO"]
        salidas_no_auth = df_filtrado[df_filtrado['Estatus'] == "SALIDA NO AUTORIZADA"]
        alerta_html = ""
        if not retardos_graves.empty:
            alerta_html += "<div style='background:#d32f2f;padding:12px;color:white;border-radius:8px;'><b>🚨 RETARDOS CRÍTICOS (>30 MIN):</b><ul>"
            for _, r in retardos_graves.iterrows(): alerta_html += f"<li>{r['Empleado']} ({r['Hora']})</li>"
            alerta_html += "</ul></div><br>"
        if not salidas_no_auth.empty:
            alerta_html += "<div style='background:#fff9c4;padding:12px;border-left:8px solid #fbc02d;color:#333;'><b>⚠️ SALIDAS NO AUTORIZADAS:</b><ul>"
            for _, s in salidas_no_auth.iterrows(): alerta_html += f"<li>{s['Empleado']} ({s['Hora']})</li>"
            alerta_html += "</ul></div>"

        csv_final = nom[['Empleado', 'Fecha', 'Entrada', 'Salida', 'Total_Horas', 'Horas_Extras', 'Min_Retardo', 'Estatus_Dia', 'Observaciones', 'Justificacion']]
        csv_final = csv_final.sort_values(by=['Empleado', 'Fecha'])

        msg = MIMEMultipart()
        msg['Subject'] = f"📊 REPORTE DE ASISTENCIA DE PERSONAL TRV - {hoy.strftime('%d/%m/%Y')}"
        cuerpo = f"<html><body style='font-family:Arial;'><div style='padding:20px;border-radius:10px;max-width:600px;border:1px solid #eee;'><h2>Resumen Semanal</h2>{alerta_html}<p>Detalle adjunto en CSV (Ordenado A-Z).</p></div></body></html>"
        msg.attach(MIMEText(cuerpo, 'html'))

        csv_data = csv_final.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(csv_data)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="REPORTE_{hoy.strftime("%d_%m")}.csv"')
        msg.attach(part)

        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(REMITENTE, PASSWORD_APP)
            s.sendmail(REMITENTE, DESTINATARIOS, msg.as_string())
        return True
    except Exception as e: return str(e)

# --- 3. DISTANCIA ---
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
                def registrar(tipo, empleado_id, lat, lon):
    # 1. Bloqueo de re-ejecución y lectura fresca
    if st.session_state.get('procesando', False):
        return
    
    st.session_state.procesando = True
    
    try:
        # Leemos la data más reciente justo antes de escribir
        df_full = conn.read(ttl=0)
        
        # Filtramos registros del empleado hoy para validar duplicados
        hoy_str = ahora.strftime("%d/%m/%Y")
        regs_hoy = df_full[
            (df_full['Empleado'] == empleado_id) & 
            (df_full['Hora'].str.contains(hoy_str))
        ]

        # 2. VALIDACIONES DE FLUJO
        if tipo == "Entrada" and "Entrada" in regs_hoy['Tipo'].values:
            st.warning(f"⚠️ {empleado_id}, ya registraste tu ENTRADA hoy.")
            st.session_state.procesando = False
            return

        if tipo == "Salida":
            if "Entrada" not in regs_hoy['Tipo'].values:
                st.error(f"❌ {empleado_id}, no puedes marcar SALIDA sin haber marcado ENTRADA.")
                st.session_state.procesando = False
                return
            if "Salida" in regs_hoy['Tipo'].values:
                st.warning(f"⚠️ {empleado_id}, ya registraste tu SALIDA hoy.")
                st.session_state.procesando = False
                return

        # 3. LÓGICA DE ESTATUS Y RETARDOS
        est, min_r = "A Tiempo", 0
        
        if tipo == "Entrada":
            h_lim = datetime.strptime(HORA_ENTRADA_OFICIAL, "%H:%M:%S").time()
            # Calculamos diferencia real en minutos
            diff = (datetime.combine(date.today(), ahora.time()) - 
                    datetime.combine(date.today(), h_lim)).total_seconds() / 60
            min_r = max(0, int(diff))
            
            if min_r > 30: est = "RETARDO CRÍTICO"
            elif min_r > UMBRAL_RETARDO_MINUTOS: est = "Retardo"
            
        elif tipo == "Salida":
            h_sal_oficial = datetime.strptime(HORA_SALIDA_OFICIAL, "%H:%M:%S").time()
            if ahora.time() < h_sal_oficial:
                est = "SALIDA ANTICIPADA" # Nueva categoría útil
            else:
                try:
                    df_m = conn.read(worksheet="Empleados", ttl=0)
                    auth = (df_m.loc[df_m['Nombre'] == empleado_id, 'Autoriza_Extra'].values == "SÍ")
                    est = "Salida Autorizada" if auth else "Salida a Tiempo"
                except: est = "Salida Registrada"

        # 4. ESCRITURA EN GOOGLE SHEETS
        nuevo_reg = pd.DataFrame([[
            empleado_id, 
            ahora.strftime("%d/%m/%Y %H:%M:%S"), 
            lat, lon, tipo, est, min_r, ""
        ]], columns=["Empleado", "Hora", "Lat", "Lon", "Tipo", "Estatus", "Min_Retardo", "Justificacion"])
        
        updated_df = pd.concat([df_full, nuevo_reg], ignore_index=True)
        conn.update(data=updated_df)

        # 5. FEEDBACK VISUAL
        if est in ["RETARDO CRÍTICO", "SALIDA ANTICIPADA"]:
            st.error(f"🚨 {empleado_id}: {est}. Se ha notificado al sistema.")
        elif est == "Retardo":
            st.warning(f"⏳ {empleado_id}, registro con {min_r} min de retardo.")
        else:
            st.success(f"✅ {tipo} registrada con éxito para {empleado_id}.")
            if tipo == "Entrada": st.balloons()
            else: st.snow()

    except Exception as e:
        st.error(f"Error al registrar: {e}")
    finally:
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
                    if enviar_reporte_semanal(df_a) is True: st.success("✅ Enviado.")
                    else: st.error("Error al enviar.")
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

