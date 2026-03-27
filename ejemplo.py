import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import pytz
from supabase import create_client
import qrcode
from io import BytesIO
import zipfile
import cv2
import numpy as np
from math import radians, cos, sin, asin, sqrt
import smtplib
from email.mime.text import MIMEText
from streamlit_js_eval import get_geolocation

# =========================
# 🔌 SUPABASE & CONFIG
# =========================
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

zona = pytz.timezone('America/Mexico_City')
HORA_ENTRADA = "07:00:00"
HORA_SALIDA = "17:00:00"

ROLES_KIOSCO = ["admin", "Supervisor OP", "Supervisor Seguridad"]
ROLES_ADMIN = ["admin"]

st.set_page_config(layout="wide", page_title="NEOMOTIC Access PRO")

# =========================
# 🧠 FUNCIONES NÚCLEO
# =========================
@st.cache_data(ttl=600)
def obtener_empleados():
    return supabase.table("empleados").select("*").execute().data

def obtener_registros_hoy():
    hoy_str = datetime.now(zona).date().isoformat()
    return pd.DataFrame(supabase.table("registros").select("*").gte("fecha_hora", hoy_str).execute().data)

def distancia_metros(lat1, lon1, lat2, lon2):
    if None in [lat1, lon1, lat2, lon2]: return 999999
    R = 6371000
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def validar_geocerca(lat, lon, sucursal_id):
    suc = supabase.table("sucursales").select("*").eq("id", sucursal_id).execute().data
    if not suc: return True
    s = suc[0]
    return distancia_metros(lat, lon, s['lat'], s['lon']) <= s.get("radio", 100)

def validar_flujo(nombre, tipo):
    try:
        # 1. Traer registros de los últimos 2 días para este empleado
        ayer_str = (datetime.now(zona).date() - timedelta(days=1)).isoformat()
        res = supabase.table("registros").select("*").eq("empleado", nombre).gte("fecha_hora", ayer_str).execute()
        
        if not res.data: 
            return True, ""
            
        df = pd.DataFrame(res.data)
        
        # 2. LIMPIEZA EXTREMA DE FECHAS (Evita el ValueError)
        # Convertimos a fecha, lo que no sea fecha se vuelve 'NaT' y luego se elimina
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce', utc=True)
        df = df.dropna(subset=['fecha_hora']) 
        
        if df.empty: return True, ""

        # 3. Convertir a hora de México
        df['fecha_hora'] = df['fecha_hora'].dt.tz_convert('America/Mexico_City')
        hoy = datetime.now(zona).date()

        # 4. Lógica de validación
        if tipo == "Salida":
            hoy_regs = df[df['fecha_hora'].dt.date == hoy]
            if not any(hoy_regs['tipo'] == "Entrada"):
                return False, "⚠️ No puedes registrar SALIDA sin haber registrado ENTRADA hoy."
        
        return True, ""

    except Exception as e:
        # Si algo falla catastróficamente, dejamos pasar el registro para no bloquear al empleado
        print(f"Error en validación: {e}")
        return True, ""


# =========================
# 📍 REGISTRAR
# =========================
def registrar(nombre, tipo):
    if st.session_state.registro_ok: return

    ok, msg = validar_flujo(nombre, tipo)
    if not ok:
        st.error(msg)
        return

    # 📡 GPS REAL (Llamativo y con Reintento)
    loc = get_geolocation()
    if not loc:
        st.error("🚨 **ERROR DE UBICACIÓN**")
        st.warning("Por favor, **activa el GPS** de tu celular y **permite el acceso** en el navegador.")
        if st.button("🔄 REINTENTAR LECTURA GPS"):
            st.rerun()
        return
    
    lat, lon = loc['coords']['latitude'], loc['coords']['longitude']

    if not validar_geocerca(lat, lon, st.session_state.user['sucursal_id']):
        st.error(f"❌ Fuera de rango (Lat: {lat:.4f}, Lon: {lon:.4f})")
        return

    ahora = datetime.now(zona)
    est, min_r = "A Tiempo", 0

    if tipo == "Entrada":
        h_lim = datetime.strptime(HORA_ENTRADA, "%H:%M:%S").replace(tzinfo=zona).time()
        diff = (datetime.combine(date.today(), ahora.time()) - datetime.combine(date.today(), h_lim)).total_seconds() / 60
        min_r = max(0, int(diff))
        if min_r > 30: est = "RETARDO CRÍTICO"
        elif min_r > 15: est = "Retardo"

    if tipo == "Salida" and ahora.time() < datetime.strptime(HORA_SALIDA, "%H:%M:%S").time():
        est = "SALIDA ANTICIPADA"

    try:
        data_ins = {
            "empleado": nombre, "fecha_hora": ahora.isoformat(), "lat": lat, "lon": lon,
            "tipo": tipo, "estatus": est, "min_retardo": min_r, 
            "sucursal_id": st.session_state.user['sucursal_id'], "justificacion": ""
        }
        res = supabase.table("registros").insert(data_ins).execute()
        st.session_state.registro_id = res.data[0]['id']
        st.session_state.registro_ok = True
        st.session_state.ultimo_movimiento = f"{tipo} registrada ✅"
        if est != "A Tiempo": st.session_state.justificar = True
        st.rerun()
    except Exception as e:
        st.error(f"Error DB: {e}")

# =========================
# 🔐 LOGIN & SESSION
# =========================
for key_s in ['user', 'justificar', 'registro_id', 'modo_kiosco', 'registro_ok', 'ultimo_movimiento']:
    if key_s not in st.session_state: st.session_state[key_s] = None if key_s != 'modo_kiosco' and key_s != 'justificar' and key_s != 'registro_ok' else False

if not st.session_state.user:
    st.title("🏢 NEOMOTIC Access PRO")
    u_input = st.text_input("Nombre")
    p_input = st.text_input("PIN", type="password")
    if st.button("Ingresar"):
        res = supabase.table("empleados").select("*").eq("nombre", u_input).eq("pin", p_input).eq("activo", True).execute()
        if res.data:
            st.session_state.user = res.data[0]
            st.rerun()
        else: st.error("❌ Datos incorrectos")
    st.stop()

# =========================
# 👤 INTERFAZ USUARIO
# =========================
user = st.session_state.user
st.title("🏢 NEOMOTIC Access PRO")
st.sidebar.success(f"👤 {user['nombre']} ({user.get('rol')})")

if st.sidebar.button("🚪 Cerrar sesión"):
    st.session_state.user = None
    st.rerun()

# MODO KIOSCO
if user.get("rol") in ROLES_KIOSCO:
    if st.sidebar.checkbox("🖥️ Activar Modo Kiosco"):
        st.session_state.modo_kiosco = True
    else: st.session_state.modo_kiosco = False

if st.session_state.modo_kiosco:
    st.header("📸 Escanea tu QR")
    foto = st.camera_input("Scanner")
    if foto:
        img = cv2.imdecode(np.asarray(bytearray(foto.getvalue()), dtype=np.uint8), 1)
        qr_data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
        if qr_data:
            st.subheader(f"Empleado: {qr_data}")
            c1, c2 = st.columns(2)
            if c1.button("📥 ENTRADA"): registrar(qr_data, "Entrada")
            if c2.button("📤 SALIDA"): registrar(qr_data, "Salida")
    
    if st.session_state.registro_ok:
        st.success(st.session_state.ultimo_movimiento)
        import time
        time.sleep(3)
        st.session_state.registro_ok = False
        st.rerun()
    st.stop()

# INTERFAZ NORMAL
if not st.session_state.registro_ok:
    c1, c2 = st.columns(2)
    if c1.button("📥 REGISTRAR ENTRADA", use_container_width=True): registrar(user['nombre'], "Entrada")
    if c2.button("📤 REGISTRAR SALIDA", use_container_width=True): registrar(user['nombre'], "Salida")
else:
    st.success(st.session_state.ultimo_movimiento)

# JUSTIFICACIÓN
if st.session_state.justificar and st.session_state.registro_id:
    with st.form("f_just"):
        motivo = st.text_area("⚠️ Explica el motivo del retardo/salida anticipada:")
        if st.form_submit_button("Enviar Justificación"):
            if len(motivo) > 5:
                supabase.table("registros").update({"justificacion": motivo}).eq("id", st.session_state.registro_id).execute()
                st.session_state.justificar = False
                st.success("Guardado"); st.rerun()
            else: st.warning("Por favor detalla más.")

# =========================
# 📊 DASHBOARD ADMIN (FILTRADO DINÁMICO)
# =========================
if user.get("rol") in ROLES_ADMIN:
    st.divider()
    st.subheader("📊 Panel de Control Administrativo")

    # 📅 Selector de Rango en el Sidebar o Main
    rango = st.selectbox("Seleccionar periodo de reporte:", 
                        ["Hoy", "Últimos 7 días", "Últimos 30 días"], index=0)

    # Calcular fecha de inicio según selección
    hoy_dt = datetime.now(zona).date()
    if rango == "Hoy":
        fecha_inicio = hoy_dt
    elif rango == "Últimos 7 días":
        fecha_inicio = hoy_dt - timedelta(days=7)
    else:
        fecha_inicio = hoy_dt - timedelta(days=30)

    # 🔍 Consulta filtrada a Supabase (Trae solo lo necesario)
    res_db = supabase.table("registros").select("*").gte("fecha_hora", fecha_inicio.isoformat()).execute()
    df_rep = pd.DataFrame(res_db.data)

    if not df_rep.empty:
        # 🛠️ Corrección de Zona Horaria (La que arreglamos antes)
        df_rep['fecha_hora'] = pd.to_datetime(df_rep['fecha_hora']).dt.tz_localize('UTC').dt.tz_convert('America/Mexico_City')
        df_rep['solo_fecha'] = df_rep['fecha_hora'].dt.date

        # 📈 Métricas Superiores
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Registros", len(df_rep))
        c2.metric("Retardos", len(df_rep[df_rep['estatus'].str.contains("Retardo|RETARDO", na=False)]))
        c3.metric("Salidas Ant.", len(df_rep[df_rep['estatus'] == "SALIDA ANTICIPADA"]))
        c4.metric("A Tiempo", len(df_rep[df_rep['estatus'] == "A Tiempo"]))

        # 📊 Gráficos Visuales
        col_g1, col_g2 = st.columns(2)
        
        with col_g1:
            st.write("📅 **Registros por Día**")
            st.bar_chart(df_rep.groupby('solo_fecha').size())

        with col_g2:
            st.write("👤 **Minutos de Retardo por Empleado**")
            # Sumamos los minutos acumulados en el periodo seleccionado
            st.bar_chart(df_rep.groupby('empleado')['min_retardo'].sum())

        # 📄 Tabla Detallada
        st.write(f"📋 **Detalle del periodo: {rango}**")
        st.dataframe(df_rep[["empleado", "fecha_hora", "tipo", "estatus", "min_retardo", "justificacion"]].sort_values("fecha_hora", ascending=False), use_container_width=True)
        
        # 📥 BOTÓN DE EXPORTAR (CORREGIDO PARA EXCEL)
        output = BytesIO()
        
        # Hacemos una copia para no afectar la visualización en la app
        df_para_excel = df_rep.copy()

        # Quitar la zona horaria de TODAS las columnas de fecha para que Excel no falle
        for col in df_para_excel.select_dtypes(include=['datetime64[ns, America/Mexico_City]', 'datetimetz']).columns:
            df_para_excel[col] = df_para_excel[col].dt.tz_localize(None)

        # Generar el archivo
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_para_excel.to_excel(writer, index=False, sheet_name='Reporte')
        
        st.download_button(
            label=f"📥 Descargar Reporte ({rango})",
            data=output.getvalue(),
            file_name=f"reporte_{rango.replace(' ', '_').lower()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    else:
        st.info(f"No hay registros encontrados para el periodo: {rango}")
        

    # =========================
    # 📦 GENERAR QR (ADMIN)
    # =========================
    if user.get("rol") in ROLES_ADMIN:
        st.divider()
        st.subheader("📦 Herramientas de Códigos QR")
    
        emps = obtener_empleados()
        if emps:
            col_qr1, col_qr2 = st.columns(2)
    
            # --- QR INDIVIDUAL ---
            with col_qr1:
                st.write("👤 **Generar QR Individual**")
                nombres_lista = [e['nombre'] for e in emps]
                sel_emp = st.selectbox("Selecciona un empleado:", nombres_lista)
                
                if sel_emp:
                    img_qr = qrcode.make(sel_emp)
                    buf_ind = BytesIO()
                    img_qr.save(buf_ind, format="PNG")
                    st.image(buf_ind.getvalue(), width=200, caption=f"QR de {sel_emp}")
                    st.download_button(f"⬇️ Descargar QR de {sel_emp}", buf_ind.getvalue(), f"QR_{sel_emp}.png", "image/png")
    
            # --- QR MASIVO (ZIP) ---
            with col_qr2:
                st.write("📦 **Descarga Masiva**")
                if st.button("Generar ZIP con todos los QR"):
                    zip_buffer = BytesIO()
                    with zipfile.ZipFile(zip_buffer, "w") as z:
                        for emp in emps:
                            nombre_e = emp['nombre']
                            qr_e = qrcode.make(nombre_e)
                            img_buf_e = BytesIO()
                            qr_e.save(img_buf_e, format='PNG')
                            z.writestr(f"QR_{nombre_e}.png", img_buf_e.getvalue())
                    
                    st.download_button(
                        "⬇️ Descargar TODO el personal (ZIP)",
                        zip_buffer.getvalue(),
                        file_name="QR_TODOS_EMPLEADOS.zip",
                        mime="application/zip"
                    )
        else:
            st.warning("No hay empleados en la base de datos para generar QR.")
