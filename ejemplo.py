import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit_js_eval import get_geolocation
import cv2
import numpy as np
import os
from math import radians, cos, sin, asin, sqrt
import pytz

# Configuración de zona horaria
zona_veracruz = pytz.timezone('America/Mexico_City')

# --- CONFIGURACIÓN DE LA OFICINA ---
OFICINA_LAT = 19.245304  
OFICINA_LON = -96.174232 
RADIO_PERMITIDO = 1000   
DB_FILE = "asistencia_geocerca.csv"

def calcular_distancia(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return c * 6371000 

st.title("📍 Registro de asistencia NEOMOTIC")

loc = get_geolocation()

if loc:
    lat_actual = loc['coords']['latitude']
    lon_actual = loc['coords']['longitude']
    
    distancia = calcular_distancia(lat_actual, lon_actual, OFICINA_LAT, OFICINA_LON)
    
    if distancia <= RADIO_PERMITIDO:
        st.success(f"✅ Estás en la zona de trabajo ({int(distancia)}m de la oficina)")
        
        foto = st.camera_input("Escanea tu QR para registrar entrada")
        if foto:
            file_bytes = np.asarray(bytearray(foto.getvalue()), dtype=np.uint8)
            img = cv2.imdecode(file_bytes, 1)
            data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)

            if data:
                # Corregida la indentación aquí abajo
                if st.button(f"Confirmar Registro para {data}"):
                    ahora_veracruz = datetime.now(zona_veracruz)
                    hora_formateada = ahora_veracruz.strftime("%d/%m/%Y %H:%M:%S")

                    nuevo = pd.DataFrame([[data, hora_formateada, lat_actual, lon_actual]], 
                                         columns=["Empleado", "Hora", "Lat", "Lon"])
                    
                    nuevo.to_csv(DB_FILE, mode='a', header=not os.path.exists(DB_FILE), index=False)
                    st.success(f"Registrado a las {hora_formateada}")
                    st.balloons()
            else:
                st.error("QR no detectado.")
    else:
        st.error(f"❌ Estás fuera de la zona. Distancia: {int(distancia)}m")
        st.info("Debes estar a menos de 1000 metros de la oficina para registrarte.")
else:
    st.warning("Esperando señal GPS... Por favor, acepta los permisos.")
    
# --- SECCIÓN DE CONSULTA ---
st.divider()
st.subheader("📋 Registros de Hoy")

if os.path.exists(DB_FILE):
    df = pd.read_csv(DB_FILE)
    
    # Intentamos convertir la hora manejando posibles errores de formato
    df['Hora'] = pd.to_datetime(df['Hora'], dayfirst=True, errors='coerce')
    
    hoy = datetime.now(zona_veracruz).date()
    df_hoy = df[df['Hora'].dt.date == hoy]
    
    if not df_hoy.empty:
        st.dataframe(df_hoy.sort_values(by="Hora", ascending=False), use_container_width=True)
        
        # --- MAPA ---
        st.subheader("🗺️ Mapa de registros")
        map_data = df_hoy[['Lat', 'Lon']].rename(columns={'Lat': 'lat', 'Lon': 'lon'})
        st.map(map_data)
    else:
        st.info("Aún no hay registros el día de hoy.")
else:
    st.info("El archivo de base de datos se creará con el primer registro.")
    
# --- PANEL DE ADMINISTRACIÓN ---
st.divider()
with st.expander("🔐 Panel de Administración de neomotic"):
    password = st.text_input("Introduce la contraseña para ver los registros", type="password")
    
    # Define aquí tu contraseña
    if password == "NEOMOTIC2026": 
        st.subheader("📋 Registros de Hoy")

        if os.path.exists(DB_FILE):
            df = pd.read_csv(DB_FILE)
            
            # Convertir a datetime manejando el formato día/mes/año
            df['Hora'] = pd.to_datetime(df['Hora'], dayfirst=True, errors='coerce')
            
            hoy = datetime.now(zona_veracruz).date()
            df_hoy = df[df['Hora'].dt.date == hoy]
            
            if not df_hoy.empty:
                # Botón para descargar el reporte en Excel/CSV
                csv = df_hoy.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Descargar Reporte de Hoy",
                    data=csv,
                    file_name=f"asistencia_{hoy}.csv",
                    mime="text/csv",
                )
                
                # Tabla
                st.dataframe(df_hoy.sort_values(by="Hora", ascending=False), use_container_width=True)
                
                
            else:
                st.info("Aún no hay registros el día de hoy.")
        else:
            st.info("No existe archivo de base de datos todavía.")
    elif password != "":
        st.error("Contraseña incorrecta")






