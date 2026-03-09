import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit_js_eval import get_geolocation
import cv2
import numpy as np
import os
from math import radians, cos, sin, asin, sqrt
import pytz
from datetime import datetime

zona_veracruz = pytz.timezone('America/Mexico_City')


# ----------------------------------
OFICINA_LAT = 19.245304  
OFICINA_LON = -96.174232 
RADIO_PERMITIDO = 1000   
# ----------------------------------

DB_FILE = "asistencia_geocerca.csv"

def calcular_distancia(lat1, lon1, lat2, lon2):
    # Fórmula de Haversine para distancia en metros
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
    if st.button(f"Confirmar Registro para {data}"):
        # 2. Obtener hora exacta de Veracruz
        ahora_veracruz = datetime.now(zona_veracruz)
        hora_formateada = ahora_veracruz.strftime("%d/%m/%Y %H:%M:%S")

        # 3. Guardar con la hora corregida
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
    
    # Convertir columna Hora a formato fecha para filtrar
    df['Hora'] = pd.to_datetime(df['Hora'])
    
    # Filtrar solo los de hoy
    hoy = datetime.now().date()
    df_hoy = df[df['Hora'].dt.date == hoy]
    
    if not df_hoy.empty:
        # Mostrar tabla limpia
        st.dataframe(df_hoy.sort_values(by="Hora", ascending=False), use_container_width=True)
    else:
        st.info("Aún no hay registros el día de hoy.")
else:
    st.info("El archivo de base de datos se creará con el primer registro.")



