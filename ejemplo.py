import streamlit as st
import pandas as pd
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
from supabase import create_client

url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]

supabase = create_client(url, key)

# --- 1. CONFIGURACIÓN INICIAL ---
zona_veracruz = pytz.timezone('America/Mexico_City')

HORA_ENTRADA_OFICIAL = "07:00:00" 
HORA_SALIDA_OFICIAL = "17:00:00" 
UMBRAL_RETARDO_MINUTOS = 15

OFICINA_LAT = 19.245304  
OFICINA_LON = -96.174232 
RADIO_PERMITIDO = 1000   

def obtener_registros():
    try:
        response = supabase.table("registros").select("*").execute()
        data = response.data
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error al leer Supabase: {e}")
        return pd.DataFrame()

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

        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.base import MIMEBase
        from email import encoders
        import smtplib

        msg = MIMEMultipart()
        msg['From'] = REMITENTE
        msg['To'] = ", ".join(DESTINATARIOS)
        msg['Subject'] = f"📊 Reporte Semanal de Asistencia - {hoy.strftime('%d/%m/%Y')}"

        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; }}
                h2 {{ color: #1a237e; border-bottom: 2px solid #1a237e; padding-bottom: 10px; }}
                .container {{ padding: 20px; }}
                .footer {{ margin-top: 30px; font-size: 11px; color: #777; font-style: italic; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>📊 Auditoría de Asistencia Semanal - TRV</h2>
                <p>Se ha generado el reporte detallado de los últimos 7 días (al {hoy.strftime('%d/%m/%Y')}).</p>
                <p><strong>Nota:</strong> Los detalles de cada empleado se encuentran adjuntos en el archivo CSV que acompaña a este correo.</p>
                <div class="footer">
                    <p>Este reporte se generó automáticamente desde el sistema NEOMOTIC Access.</p>
                </div>
            </div>
        </body>
        </html>
        """
        msg.attach(MIMEText(html, 'html'))

        csv_data = df_final.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(csv_data)
        encoders.encode_base64(part)
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

# Inicialización de estados
if 'procesando' not in st.session_state: st.session_state.procesando = False
if 'necesita_justificar' not in st.session_state: st.session_state.necesita_justificar = False
if 'ubicacion_ok' not in st.session_state: st.session_state.ubicacion_ok = False

st.title("📍 Asistencia Personal TRV")

       # --- PASO 1: VERIFICACIÓN DE UBICACIÓN ---
if not st.session_state.ubicacion_ok:
    with st.status("Verificando ubicación GPS...", expanded=True) as status:
        loc = get_geolocation()
        if not loc:
            st.warning("⚠️ Por favor, activa el GPS y permite el acceso.")
            st.stop()
        
        lat_act, lon_act = loc['coords']['latitude'], loc['coords']['longitude']
        dist = calcular_distancia(lat_act, lon_act, OFICINA_LAT, OFICINA_LON)
        
        if dist <= RADIO_PERMITIDO:
            st.session_state.ubicacion_ok = True
            st.session_state.lat_act = lat_act
            st.session_state.lon_act = lon_act
            st.session_state.dist_actual = dist
            status.update(label="📍 Ubicación confirmada", state="complete")
            st.rerun()
        else:
            st.error(f"🚫 Fuera de rango: Estás a {dist/1000:.2f}km. (Máximo 100m)")
            if st.button("🔄 Reintentar Ubicación"): st.rerun()
            st.stop()

     # --- PASO 2: INTERFAZ DE REGISTRO (Solo si la ubicación es OK) ---
if st.session_state.ubicacion_ok:
    st.success(f"✅ Ubicación validada: a {int(st.session_state.dist_actual)}m de la oficina.")
    
            # 2a. Cámara y QR
    foto = st.camera_input("Escanea QR")
    if st.button("🔄 Limpiar cámara"):
        st.session_state.procesando = False
        st.rerun()
    
    if foto and not st.session_state.procesando:
        img = cv2.imdecode(np.asarray(bytearray(foto.getvalue()), dtype=np.uint8), 1)
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
        
        if data:
            st.subheader(f"👤 Empleado detectado: {data}")
            
            # Definir función de registro dentro del flujo del empleado
            def registrar(tipo):
                ahora = datetime.now(zona_veracruz)
                st.session_state.procesando = True
            
                # Leer último registro desde Supabase (opcional después)
                # Por ahora solo advertimos sin bloquear
            
                # ⚠️ Validación (solo aviso, no bloquea)
                try:
                    df_act = obtener_registros()
                    ult_reg = df_act[df_act['empleado'] == data].tail(1)

                    if tipo == "Entrada" and not ult_reg.empty and ult_reg['tipo'].values[0] == "Entrada":
                        st.warning(f"⚠️ {data}, no marcaste SALIDA anterior. Se registrará de todos modos.")
                except:
                    pass
            
                # 🔢 Cálculo de estatus
                est, min_r = "A Tiempo", 0
            
                if tipo == "Entrada":
                    h_lim = datetime.strptime(HORA_ENTRADA_OFICIAL, "%H:%M:%S").time()
                    diff = (datetime.combine(date.today(), ahora.time()) - datetime.combine(date.today(), h_lim)).total_seconds() / 60
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
            
                # 💾 GUARDAR EN SUPABASE
                try:
                    response = supabase.table("registros").insert({
                        "empleado": data,
                        "fecha_hora": ahora.strftime("%Y-%m-%d %H:%M:%S"),
                        "lat": st.session_state.lat_act,
                        "lon": st.session_state.lon_act,
                        "tipo": tipo,
                        "estatus": est,
                        "min_retardo": min_r,
                        "justificacion": ""
                    }).execute()
                
                    st.success("✅ Guardado en Supabase")

                    # 🔥 Activar justificación si aplica
                    if est in ["RETARDO CRÍTICO", "Retardo", "SALIDA NO AUTORIZADA", "SALIDA ANTICIPADA"]:
                        st.session_state.necesita_justificar = True
                        st.session_state.ultimo_empleado = data
                        st.session_state.ultima_hora = ahora.strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 🔥 Reset para permitir siguiente escaneo
                    st.session_state.procesando = False
                    
                    st.rerun()

                    if est in ["RETARDO CRÍTICO", "Retardo", "SALIDA NO AUTORIZADA", "SALIDA ANTICIPADA"]:
                        st.session_state.necesita_justificar = True
                        st.session_state.ultimo_empleado = data
                        st.session_state.ultima_hora = ahora.strftime("%Y-%m-%d %H:%M:%S")
                    
                    st.rerun()
            
                except Exception as e:
                    st.error(f"❌ ERROR REAL: {e}")
            
                st.session_state.procesando = False
                st.rerun()
 
            # Botones de acción
            c1, c2 = st.columns(2)
            c1.button("📥 ENTRADA", on_click=registrar, args=("Entrada",), use_container_width=True)
            c2.button("📤 SALIDA", on_click=registrar, args=("Salida",), use_container_width=True)

    
    # --- PASO 3: FORMULARIO DE JUSTIFICACIÓN (Fuera de la cámara) ---

    if st.session_state.necesita_justificar:
        st.divider()
    with st.form("form_j"):
        st.warning(f"⚠️ JUSTIFICACIÓN REQUERIDA: {st.session_state.ultimo_empleado}")
        motivo = st.text_area("Explica el motivo de la incidencia:")

        if st.form_submit_button("✅ Guardar y Finalizar"):
            if len(motivo) > 4:
                try:
                    response = (
                        supabase
                        .table("registros")
                        .update({
                            "justificacion": motivo
                        })
                        .eq("empleado", st.session_state.ultimo_empleado)
                        .eq("fecha_hora", st.session_state.ultima_hora)
                        .execute()
                    )

                    st.success("✅ Justificación guardada")

                    # 🔥 RESET TOTAL
                    st.session_state.necesita_justificar = False
                    st.session_state.procesando = False

                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Error: {e}")
            else:
                st.error("⚠️ Escribe un motivo más detallado.")
    


# --- 5. PANEL ADMIN (Asegúrate de que esté al final del archivo) ---

st.divider()
with st.expander("🔐 Administración"):
    # Input de contraseña para proteger los datos
    if st.text_input("Password", type="password", key="p_adm") == "NEOMOTIC2024":
        
        # Lectura de datos frescos de la sábana principal
        df_a = obtener_registros()
        
        if df_a.empty:
             st.warning("No hay registros aún")
             st.stop()
            
        df_a['fecha_hora'] = pd.to_datetime(df_a['fecha_hora'])
        
        # Obtener lista de empleados desde la pestaña 'Empleados'
        try: 
            df_empl = conn.read(worksheet="Empleados", ttl=0)
            lista_m = df_empl['Nombre'].tolist()
        except: 
            lista_m = []
        
        # Pestañas de gestión
        t1, t2, t3, t4 = st.tabs(["📋 Hoy", "🚫 Faltantes", "🗺️ Mapa", "🖨️ Generar QR"])
        
        # Procesamiento de fechas para filtrar "Hoy"
        df_a['fecha_hora'] = pd.to_datetime(df_a['fecha_hora'])
        df_h = df_a[df_a['fecha_hora'].dt.date == ahora.date()]

        with t1: 
            # Tabla de registros del día incluyendo la nueva columna Justificacion
            st.dataframe(df_h[['empleado', 'fecha_hora', 'tipo', 'estatus', 'justificacion']], use_container_width=True)
            
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
                llegaron = df_h[df_h['tipo'] == 'Entrada']['empleado'].unique()
                faltan = [e for e in lista_m if e not in llegaron]
                if faltan:
                    for f in faltan: st.write(f"❌ {f}")
                else:
                    st.success("¡Personal completo hoy!")
            else:
                st.info("Carga la lista de nombres en la pestaña 'empleados' para ver faltantes.")

        with t3:
            
           pts = df_h.dropna(subset=['lat', 'lon']).copy()
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
