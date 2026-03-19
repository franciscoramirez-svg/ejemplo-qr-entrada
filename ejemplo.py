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
# --- 2. FUNCIÓN DE CORREO (ACTUALIZADA: DETECTA DÍAS NO LABORADOS) ---
def enviar_reporte_semanal(df_registros):
    try:
        REMITENTE = st.secrets["EMAIL_USER"]
        PASSWORD_APP = st.secrets["EMAIL_PASSWORD"]
        DESTINATARIOS = ["francisco.ramirez@neomotic.com", "rodolfo.fuentes@neomotic.com"]
        
        hoy = datetime.now(zona_veracruz)
        # Rango de los últimos 7 días
        dias_reporte = [(hoy - timedelta(days=i)).date() for i in range(1, 8)]
        
        # Cargar Lista Maestra de Empleados
        try: 
            df_m = conn.read(worksheet="Empleados", ttl=0)
            lista_maestra = df_m['Nombre'].tolist()
        except: 
            return "Error: No se encontró la pestaña 'Empleados'."

        # Preparar registros existentes
        df_temp = df_registros.copy()
        df_temp['Hora_dt'] = pd.to_datetime(df_temp['Hora'], dayfirst=True, errors='coerce')
        df_temp['Fecha'] = df_temp['Hora_dt'].dt.date
        
        # Crear estructura base para el reporte (Empleado x Día)
        reporte_data = []
        for emp in lista_maestra:
            for fecha in dias_reporte:
                # Filtrar registros de este empleado en este día
                regs = df_temp[(df_temp['Empleado'] == emp) & (df_temp['Fecha'] == fecha)]
                
                if regs.empty:
                    # SI NO HAY REGISTROS, MARCAR COMO NO LABORADO
                    reporte_data.append({
                        'Empleado': emp,
                        'Fecha': fecha.strftime("%d/%m/%Y"),
                        'Entrada': '---',
                        'Salida': '---',
                        'Estatus': 'DÍA NO LABORADO',
                        'Observaciones': 'Sin registros en sistema'
                    })
                else:
                    # SI HAY REGISTROS, PROCESAR NORMAL
                    entrada = regs[regs['Tipo'] == 'Entrada']['Hora_dt'].min()
                    salida = regs[regs['Tipo'] == 'Salida']['Hora_dt'].max()
                    estatus = regs['Estatus'].iloc[0]
                    just = regs['Justificacion'].iloc[0] if 'Justificacion' in regs.columns else ""
                    
                    reporte_data.append({
                        'Empleado': emp,
                        'Fecha': fecha.strftime("%d/%m/%Y"),
                        'Entrada': entrada.strftime("%H:%M:%S") if pd.notnull(entrada) else "MISSING",
                        'Salida': salida.strftime("%H:%M:%S") if pd.notnull(salida) else "MISSING",
                        'Estatus': estatus,
                        'Observaciones': f"Justificación: {just}" if just else "OK"
                    })

        df_final = pd.DataFrame(reporte_data)

        # Enviar Correo
        # --- GENERACIÓN DE ESTILOS VISUALES PARA EL CORREO ---
        def asignar_color(row):
            est = str(row['Estatus']).upper()
            # Rojo para faltas o alertas graves
            if "DÍA NO LABORADO" in est or "RETARDO CRÍTICO" in est or "SALIDA NO AUTORIZADA" in est:
                return ['background-color: #f8d7da; color: #721c24; font-weight: bold; border: 1px solid #f5c6cb'] * len(row)
            # Amarillo para incidencias leves
            elif "RETARDO" in est or "SALIDA ANTICIPADA" in est or "MISSING" in str(row['Entrada']):
                return ['background-color: #fff3cd; color: #856404; border: 1px solid #ffeeba'] * len(row)
            # Verde para asistencia correcta
            else:
                return ['background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb'] * len(row)

        # Convertir DataFrame a HTML con estilos CSS embebidos
        html_tabla = df_final.style.apply(asignar_color, axis=1).hide(axis='index').to_html()

        # Cuerpo del mensaje con diseño profesional
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; }}
                h2 {{ color: #1a237e; border-bottom: 2px solid #1a237e; padding-bottom: 10px; }}
                .container {{ padding: 20px; }}
                table {{ border-collapse: collapse; width: 100%; margin-top: 20px; font-size: 13px; }}
                th {{ background-color: #1a237e; color: white; padding: 12px; text-align: left; }}
                td {{ padding: 10px; }}
                .footer {{ margin-top: 30px; font-size: 11px; color: #777; font-style: italic; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>📊 Auditoría de Asistencia Semanal - TRV</h2>
                <p>Resumen detallado de los últimos 7 días (al {hoy.strftime('%d/%m/%Y')}):</p>
                {html_tabla}
                <div class="footer">
                    <p>Este reporte se generó automáticamente desde el sistema NEOMOTIC Access.<br>
                    Los días marcados en ROJO requieren revisión inmediata del administrador.</p>
                </div>
            </div>
        </body>
        </html>
        """

        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.base import MIMEBase
        from email import encoders

        msg = MIMEMultipart()
        msg['From'] = REMITENTE
        msg['To'] = ", ".join(DESTINATARIOS)
        msg['Subject'] = f"📊 Reporte Semanal de Asistencia - {hoy.strftime('%d/%m/%Y')}"

        msg.attach(MIMEText(html, 'html'))

        csv_data = df_final.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(csv_data); encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="Reporte_Asistencia_TRV.csv"')
        msg.attach(part)

        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls(); s.login(REMITENTE, PASSWORD_APP)
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

# Inicialización de estados para justificación
if 'procesando' not in st.session_state: st.session_state.procesando = False
if 'necesita_justificar' not in st.session_state: st.session_state.necesita_justificar = False

st.title("📍 Asistencia Personal TRV")

    # Nueva lógica de verificación con estado visual
with st.status("Verificando ubicación GPS...", expanded=False) as status:
    loc = get_geolocation()
    if not loc:
        st.warning("⚠️ Por favor, activa el GPS y permite el acceso en tu navegador.")
        st.stop() # Esto evita que el resto de la app cargue sin GPS
    status.update(label="📍 Ubicación confirmada", state="complete")
    
    if loc:
        lat_act, lon_act = loc['coords']['latitude'], loc['coords']['longitude']
        dist = calcular_distancia(lat_act, lon_act, OFICINA_LAT, OFICINA_LON)
    
        if dist <= RADIO_PERMITIDO:
           st.success(f"✅ Estás a {int(dist)}m de la oficina. Puedes registrarte.")
    
           foto = st.camera_input("Escanea QR")
           if foto and not st.session_state.procesando:
              img = cv2.imdecode(np.asarray(bytearray(foto.getvalue()), dtype=np.uint8), 1)
              data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
              data, bbox, _ = cv2.QRCodeDetector().detectAndDecode(img)
               
              if data:
                st.success(f"📱 QR Detectado: {data}") # Feedback inmediato para el usuario
            
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
                            if ahora.time() < h_sal: est = "SALIDA ANTICIPADA" # Nueva incidencia
                            elif ahora.time() > h_sal:
                                try:
                                    df_m = conn.read(worksheet="Empleados", ttl=0)
                                    auth = (df_m.loc[df_m['Nombre'] == data, 'Autoriza_Extra'].values == "SÍ")
                                    est = "Salida Autorizada" if auth else "SALIDA NO AUTORIZADA"
                                except: est = "Error Validación"
                            else: est = "Salida a Tiempo"

                        # Guardar registro
                        nuevo = pd.DataFrame([[data, ahora.strftime("%d/%m/%Y %H:%M:%S"), lat_act, lon_act, tipo, est, min_r, ""]], 
                                             columns=["Empleado", "Hora", "Lat", "Lon", "Tipo", "Estatus", "Min_Retardo", "Justificacion"])
                        _ = conn.update(data=pd.concat([df_act, nuevo], ignore_index=True))
                        
                        # Activar bandera de justificación si hay incidencia
                        incidencias = ["RETARDO CRÍTICO", "Retardo", "SALIDA NO AUTORIZADA", "SALIDA ANTICIPADA"]
                        if est in incidencias:
                            st.session_state.necesita_justificar = True
                            st.session_state.ultimo_empleado = data
                            st.session_state.ultima_hora = ahora.strftime("%d/%m/%Y %H:%M:%S")

                        # Feedback visual
                        if est in ["RETARDO CRÍTICO", "SALIDA NO AUTORIZADA"]:
                            st.error(f"🚨 {data}: {est}.")
                        else:
                            st.success(f"✅ {tipo} registrada para {data}")
                    
                    st.session_state.procesando = False

                st.subheader(f"Empleado: {data}")
                c1, c2 = st.columns(2)
                c1.button("📥 ENTRADA", on_click=registrar, args=("Entrada",), use_container_width=True)
                c2.button("📤 SALIDA", on_click=registrar, args=("Salida",), use_container_width=True)

         
               # --- APARTADO DE JUSTIFICACIÓN (Se activa tras el registro)  ---
        
        if st.session_state.get('necesita_justificar', False):
            st.divider() # Separador visual
            with st.form("form_j"):
                st.warning(f"⚠️ JUSTIFICACIÓN REQUERIDA: {st.session_state.ultimo_empleado}")
                st.info(f"Registro detectado a las: {st.session_state.ultima_hora}")
                
                # Usamos text_area para que tengan espacio de escribir bien
                motivo = st.text_area("Explica el motivo de la incidencia (Retardo/Salida):", placeholder="Ej: Tráfico intenso en zona norte...")
                
                if st.form_submit_button("✅ Guardar y Finalizar"):
                    if len(motivo) > 4: # Validación mínima de caracteres
                        # Leemos datos frescos para asegurar que el registro existe
                        df_j = conn.read(ttl=0)
                        
                        # Máscara de búsqueda precisa
                        mask = (df_j['Empleado'] == st.session_state.ultimo_empleado) & \
                               (df_j['Hora'] == st.session_state.ultima_hora)
                        
                        if mask.any():
                            df_j.loc[mask, 'Justificacion'] = motivo
                            conn.update(data=df_j)
                            
                            # Limpiamos estados para permitir nuevos registros
                            st.session_state.necesita_justificar = False
                            st.session_state.ultimo_empleado = None
                            st.session_state.ultima_hora = None
                            
                            st.success("✅ Justificación guardada. Registro completado.")
                            st.rerun()
                        else:
                            st.error("❌ Error crítico: No se encontró el registro para justificar. Contacta a sistemas.")
                    else:
                        st.error("⚠️ Por favor, escribe una justificación válida (mínimo 5 letras).")

    else: 
        st.error(f"🚫 Fuera de rango: Estás a {dist/1000:.2f}km. Debes estar a menos de 100 metros.")
        if st.button("🔄 Reintentar Ubicación"):
           st.rerun()

# --- 5. PANEL ADMIN (Asegúrate de que esté al final del archivo) ---

st.divider()
with st.expander("🔐 Administración"):
    # Input de contraseña para proteger los datos
    if st.text_input("Password", type="password", key="p_adm") == "NEOMOTIC2024":
        
        # Lectura de datos frescos de la sábana principal
        df_a = conn.read(ttl=0)
        
        # Obtener lista de empleados desde la pestaña 'Empleados'
        try: 
            df_empl = conn.read(worksheet="Empleados", ttl=0)
            lista_m = df_empl['Nombre'].tolist()
        except: 
            lista_m = []
        
        # Pestañas de gestión
        t1, t2, t3, t4 = st.tabs(["📋 Hoy", "🚫 Faltantes", "🗺️ Mapa", "🖨️ Generar QR"])
        
        # Procesamiento de fechas para filtrar "Hoy"
        df_a['Hora_dt'] = pd.to_datetime(df_a['Hora'], dayfirst=True, errors='coerce')
        df_h = df_a[df_a['Hora_dt'].dt.date == ahora.date()].copy()

        with t1: 
            # Tabla de registros del día incluyendo la nueva columna Justificacion
            st.dataframe(df_h[['Empleado', 'Hora', 'Tipo', 'Estatus', 'Justificacion']], use_container_width=True)
            
                       # --- BOTÓN DE DESCARGA EXCEL ---
            import io
            buffer = io.BytesIO()
            # Usamos xlsxwriter para que el archivo sea compatible con todo
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                df_h.to_excel(writer, sheet_name='Asistencia_Hoy', index=False)
                # Auto-ajuste de columnas para que se vea ordenado
                worksheet = writer.sheets['Asistencia_Hoy']
                for i, col in enumerate(df_h.columns):
                    column_len = max(df_h[col].astype(str).map(len).max(), len(col)) + 2
                    worksheet.set_column(i, i, column_len)

            st.download_button(
                label="📥 Descargar Reporte Hoy (Excel)",
                data=buffer.getvalue(),
                file_name=f"Asistencia_{ahora.strftime('%d_%m_%Y')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

            st.divider() # Un separador visual para orden

            # 3. BOTÓN DE ENVÍO POR CORREO (El que ya tenías, pero asegúrate de que esté aquí)
            if st.button("📧 Enviar Reporte Semanal a Directivos", key="btn_final_report", use_container_width=True):
                with st.spinner("Generando reporte con colores y enviando..."):
                    # Esta función usa el nuevo diseño HTML que mejoramos antes
                    res = enviar_reporte_semanal(df_a)
                    if res is True: 
                        st.success("✅ ¡Reporte enviado con éxito a los correos configurados!")
                    else: 
                        st.error(f"❌ Error al enviar el correo: {res}")

        with t2:
            # Lógica de quién no ha checado entrada hoy
            if lista_m:
                llegaron = df_h[df_h['Tipo'] == 'Entrada']['Empleado'].unique()
                faltan = [e for e in lista_m if e not in llegaron]
                if faltan:
                    for f in faltan: st.write(f"❌ {f}")
                else:
                    st.success("¡Personal completo hoy!")
            else:
                st.info("Carga la lista de nombres en la pestaña 'Empleados' para ver faltantes.")

        with t3:
            
           pts = df_h.dropna(subset=['Lat', 'Lon']).copy()
           if not pts.empty:
               pts = pts.rename(columns={'Lat': 'lat', 'Lon': 'lon'})
        # Mostramos un mapa con puntos más grandes y color
               st.map(pts, size=20, color='#0000FF') 
           else: 
               st.info("Sin registros con GPS hoy.")

        with t4:
            # Generador de códigos QR para nuevos empleados
            st.subheader("Generador de QR Nativo")
            emp_sel = st.selectbox("Selecciona Empleado:", lista_m) if lista_m else st.text_input("Nombre:")
            if emp_sel and st.button("Generar QR"):
                qr = qrcode.QRCode(version=1, box_size=10, border=4)
                qr.add_data(emp_sel)
                qr.make(fit=True)
                buf = BytesIO()
                qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
                st.image(buf.getvalue(), caption=f"QR de {emp_sel}", width=250)

