import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from datetime import datetime
from streamlit_js_eval import get_geolocation
import cv2
import numpy as np
from math import radians, cos, sin, asin, sqrt
import pytz

# 1. Configuración de zona horaria y Conexión
zona_veracruz = pytz.timezone('America/Mexico_City')
conn = st.connection("gsheets", type=GSheetsConnection)

# --- CONFIGURACIÓN DE LA OFICINA ---
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

st.title("📍 Registro de asistencia NEOMOTIC")

loc = get_geolocation()

if loc:
    lat_actual = loc['coords']['latitude']
    lon_actual = loc['coords']['longitude']
    distancia = calcular_distancia(lat_actual, lon_actual, OFICINA_LAT, OFICINA_LON)
    
    if distancia <= RADIO_PERMITIDO:
        st.success(f"✅ Estás en la zona de trabajo ({int(distancia)}m)")
        foto = st.camera_input("Escanea tu QR para registrar asistencia")
        
        if foto:
            file_bytes = np.asarray(bytearray(foto.getvalue()), dtype=np.uint8)
            img = cv2.imdecode(file_bytes, 1)
            data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)

            if data:
                # 2. Lógica de botones Entrada/Salida
                df_actual = conn.read(ttl=0)
                ahora_veracruz = datetime.now(zona_veracruz)
                fecha_hoy = ahora_veracruz.strftime("%d/%m/%Y")
                hora_formateada = ahora_veracruz.strftime("%d/%m/%Y %H:%M:%S")

                st.subheader(f"Empleado: {data}")
                col1, col2 = st.columns(2)

                with col1:
                    if st.button("📥 Registrar ENTRADA"):
                        # Validar si ya existe entrada hoy
                        ya_entro = not df_actual[(df_actual['Empleado'] == data) & 
                                               (df_actual['Hora'].str.contains(fecha_hoy)) & 
                                               (df_actual['Tipo'] == 'Entrada')].empty
                        if ya_entro:
                            st.warning(f"⚠️ {data}, ya registraste entrada hoy.")
                        else:
                            nuevo = pd.DataFrame([[data, hora_formateada, lat_actual, lon_actual, "Entrada"]], 
                                                 columns=["Empleado", "Hora", "Lat", "Lon", "Tipo"])
                            df_final = pd.concat([df_actual, nuevo], ignore_index=True)
                            conn.update(data=df_final)
                            st.success("✅ Entrada registrada exitosamente")
                            st.balloons()

                with col2:
                    if st.button("📤 Registrar SALIDA"):
                        # Validar si ya existe salida hoy
                        ya_salio = not df_actual[(df_actual['Empleado'] == data) & 
                                                (df_actual['Hora'].str.contains(fecha_hoy)) & 
                                                (df_actual['Tipo'] == 'Salida')].empty
                        if ya_salio:
                            st.warning(f"⚠️ {data}, ya registraste salida hoy.")
                        else:
                            nuevo = pd.DataFrame([[data, hora_formateada, lat_actual, lon_actual, "Salida"]], 
                                                 columns=["Empleado", "Hora", "Lat", "Lon", "Tipo"])
                            df_final = pd.concat([df_actual, nuevo], ignore_index=True)
                            conn.update(data=df_final)
                            st.success("✅ Salida registrada exitosamente")
                            st.snow()
            else:
                st.error("QR no detectado.")
    else:
        st.error(f"❌ Fuera de zona. Distancia: {int(distancia)}m")
else:
    st.warning("Esperando señal GPS... Por favor, acepta los permisos.")

# --- PANEL DE ADMINISTRACIÓN ---
st.divider()
with st.expander("🔐 Panel de Administración"):
    password = st.text_input("Contraseña", type="password")
    
    if password == "NEOMOTIC2024": 
        df_nube = conn.read(ttl=0)
        
        if not df_nube.empty:
            # Convertir para el filtro visual
            df_nube['Hora_dt'] = pd.to_datetime(df_nube['Hora'], dayfirst=True, errors='coerce')
            hoy = datetime.now(zona_veracruz).date()
            df_hoy = df_nube[df_nube['Hora_dt'].dt.date == hoy]
            
            st.subheader(f"📋 Registros de hoy ({hoy})")
            if not df_hoy.empty:
                # Mostrar columnas originales incluyendo 'Tipo'
                st.dataframe(df_hoy[["Empleado", "Hora", "Tipo", "Lat", "Lon"]].sort_values(by="Hora", ascending=False), use_container_width=True)
                st.subheader("🗺️ Mapa de ubicaciones")
                st.map(df_hoy[['Lat', 'Lon']].rename(columns={'Lat': 'lat', 'Lon': 'lon'}))
            else:
                st.info("No hay registros hoy.")
        else:
            st.info("La base de datos está vacía.")
