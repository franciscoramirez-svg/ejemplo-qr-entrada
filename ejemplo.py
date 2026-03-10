import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime, timedelta
from streamlit_js_eval import get_geolocation
import cv2
import numpy as np
from math import radians, cos, sin, asin, sqrt
import pytz

# --- 1. CONFIGURACIÓN INICIAL ---
zona_veracruz = pytz.timezone('America/Mexico_City')
conn = st.connection("gsheets", type=GSheetsConnection)

OFICINA_LAT = 19.245304  
OFICINA_LON = -96.174232 
RADIO_PERMITIDO = 1000   

def calcular_distancia(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return c * 6371000 

st.set_page_config(page_title="NEOMOTIC Access", page_icon="📍")
st.title("📍 Registro de Asistencia Pro")

# --- 2. GESTIÓN DE ESTADO (PREVIENE DUPLICADOS POR CLIC) ---
if 'procesando' not in st.session_state:
    st.session_state.procesando = False

loc = get_geolocation()

if loc:
    lat_actual = loc['coords']['latitude']
    lon_actual = loc['coords']['longitude']
    accuracy = loc['coords'].get('accuracy', 0) # Mejora: Validar precisión GPS
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
                ahora = datetime.now(zona_veracruz)
                fecha_hoy = ahora.strftime("%d/%m/%Y")
                hora_str = ahora.strftime("%d/%m/%Y %H:%M:%S")

                st.subheader(f"Empleado: {data}")
                col1, col2 = st.columns(2)

                # --- LÓGICA DE REGISTRO OPTIMIZADA ---
                def registrar(tipo):
                    st.session_state.procesando = True
                    # Evitar registros dobles en el mismo minuto
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
                        st.toast(f"¡{tipo} registrada!", icon="🚀")
                        if tipo == "Entrada": st.balloons() 
                        else: st.snow()
                    st.session_state.procesando = False

                with col1:
                    st.button("📥 ENTRADA", on_click=registrar, args=("Entrada",), use_container_width=True)
                with col2:
                    st.button("📤 SALIDA", on_click=registrar, args=("Salida",), use_container_width=True)
            else:
                st.error("QR no legible.")
    else:
        st.error(f"Fuera de rango ({int(distancia)}m). Acércate a la oficina.")
else:
    st.info("Obteniendo ubicación...")

# --- 3. PANEL ADMIN MEJORADO CON CÁLCULO DE HORAS ---
st.divider()
with st.expander("🔐 Panel de Administración"):
    if st.text_input("Contraseña", type="password") == "NEOMOTIC2024":
        df_admin = conn.read(ttl=0)
        if not df_admin.empty:
            df_admin['Hora_dt'] = pd.to_datetime(df_admin['Hora'], dayfirst=True)
            
            # Filtro por día
            fecha_sel = st.date_input("Consultar día:", datetime.now(zona_veracruz))
            df_dia = df_admin[df_admin['Hora_dt'].dt.date == fecha_sel]
            
            # Mejora: Cálculo de Horas Trabajadas
            if not df_dia.empty:
                resumen = []
                for emp in df_dia['Empleado'].unique():
                    d_emp = df_dia[df_dia['Empleado'] == emp]
                    entrada = d_emp[d_emp['Tipo'] == 'Entrada']['Hora_dt'].min()
                    salida = d_emp[d_emp['Tipo'] == 'Salida']['Hora_dt'].max()
                    
                    horas = (salida - entrada).total_seconds()/3600 if pd.notnull(salida) and pd.notnull(entrada) else 0
                    resumen.append({"Empleado": emp, "Entrada": entrada, "Salida": salida, "Horas": round(horas, 2)})
                
                st.table(pd.DataFrame(resumen))
                
                # Mejora: Exportar a CSV
                csv = df_dia.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Descargar Reporte CSV", csv, f"reporte_{fecha_sel}.csv", "text/csv")
            else:
                st.info("Sin registros para este día.")
