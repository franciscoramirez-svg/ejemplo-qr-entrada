import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit_js_eval import get_geolocation
import cv2
import numpy as np
import os
from math import radians, cos, sin, asin, sqrt

# --- CONFIGURACIÓN DE LA OFICINA ---
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

st.title("📍 Registro de entrada")

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
                    # Guardar en CSV
                    nuevo = pd.DataFrame([[data, datetime.now(), lat_actual, lon_actual]], 
                                         columns=["Empleado", "Hora", "Lat", "Lon"])
                    nuevo.to_csv(DB_FILE, mode='a', header=not os.path.exists(DB_FILE), index=False)
                    st.balloons()
            else:
                st.error("QR no detectado.")
    else:
        st.error(f"❌ Estás fuera de la zona. Distancia: {int(distancia)}m")
        st.info("Debes estar a menos de 100 metros de la oficina para registrarte.")
else:
    st.warning("Esperando señal GPS... Por favor, acepta los permisos.")
