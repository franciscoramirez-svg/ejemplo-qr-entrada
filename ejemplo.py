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
import plotly.express as px
import time
import hashlib
import hmac


# =========================
# 🔌 SUPABASE
# =========================
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

# =========================
# ⚙️ CONFIG
# =========================
zona = pytz.timezone('America/Mexico_City')
HORA_ENTRADA = "07:00:00"
HORA_SALIDA = "17:00:00"

# 🔐 ROLES PRO
ROLES_KIOSCO = ["admin", "Supervisor OP", "Supervisor Seguridad"]
ROLES_ADMIN = ["admin"]

# =========================
# 📡 GEO
# =========================
def obtener_gps():
    try:
        params = st.query_params
        lat = float(params.get("lat", 19.24))
        lon = float(params.get("lon", -96.17))
        return lat, lon
    except (TypeError, ValueError):
        return 19.24, -96.17
        
def distancia_metros(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))


def validar_geocerca(lat, lon, sucursal_id):
    
    # 🚨 VALIDACIÓN NUEVA
    if not sucursal_id:
        return False, "❌ No tienes sucursal asignada"

    suc = supabase.table("sucursales")\
        .select("*")\
        .eq("id", sucursal_id)\
        .execute().data

    if not suc:
        return False, "❌ Sucursal no registrada en sistema"

    s = suc[0]

    dist = distancia_metros(lat, lon, s['lat'], s['lon'])

    if dist > s.get("radio", 100):
        return False, "❌ Estás fuera de la sucursal"

    return True, ""

# =========================
# 🧠 FUNCIONES
# =========================
def obtener_registros():
    return pd.DataFrame(supabase.table("registros").select("*").execute().data)

def obtener_empleados():
    return supabase.table("empleados").select("*").execute().data

def validar_pin(empleado, pin_input):
    """
    Soporta transición de PIN en texto plano a hash SHA-256:
    - Si existe `pin_hash` (hex), valida contra hash SHA-256 del input.
    - Si no existe, usa `pin` legado en texto plano.
    """
    pin_hash = empleado.get("pin_hash")
    if pin_hash:
        pin_input_hash = hashlib.sha256(pin_input.encode("utf-8")).hexdigest()
        return hmac.compare_digest(pin_input_hash, str(pin_hash))

    pin_legacy = empleado.get("pin")
    if pin_legacy is None:
        return False
    return hmac.compare_digest(str(pin_legacy), pin_input)

# =========================
#🧾 EXPORTACIÓN EXCEL
# =========================
def exportar_excel(df):

    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    st.download_button(
        "⬇️ Descargar Excel",
        data=output.getvalue(),
        file_name="reporte_asistencia.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# =========================
# 📧 EMAIL
# =========================
def enviar_reporte_diario(df_hoy):

    if df_hoy.empty:
        st.warning("No hay registros hoy")
        return

    # 📊 Excel solo de HOY
    output = BytesIO()
    df_hoy.to_excel(output, index=False)
    output.seek(0)

    hoy_str = datetime.now(zona).strftime("%Y-%m-%d")

    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email import encoders

    mensaje = MIMEMultipart()
    mensaje['Subject'] = f"📊 Reporte Diario de Asistencia - TRV - {hoy_str}"
    smtp_user = st.secrets.get("SMTP_USER")
    smtp_pass = st.secrets.get("SMTP_PASSWORD")
    email_to = st.secrets.get("REPORTE_DIARIO_TO")

    if not smtp_user or not smtp_pass or not email_to:
        st.error("Faltan credenciales de correo en secrets: SMTP_USER, SMTP_PASSWORD, REPORTE_DIARIO_TO")
        return

    mensaje['From'] = smtp_user
    mensaje['To'] = email_to

    
    retardos = len(df_hoy[df_hoy['estatus'].str.contains("Retardo|CRÍTICO", na=False)])
    faltas = "a futuro"
    total_registros = len(df_hoy)
    
    mensaje.attach(MIMEText("Buena tarde,\n\n"
                            "Se adjunta el reporte diario de asistencia." 
                            f" Resumen del día:\n\n"
                            f"📝 Total registros: {total_registros}\n"
                            f"⏰ Retardos: {retardos}\n"
                            f"🚫 Faltantes: {faltas}\n"
                            f"\n"
                            f"Sistema NEOMOTIC ACCESS PRO"
    ))
    

    part = MIMEBase('application', 'octet-stream')
    part.set_payload(output.getvalue())
    encoders.encode_base64(part)
    part.add_header(
        'Content-Disposition',
        f'attachment; filename="reporte_{hoy_str}.xlsx"'
    )

    mensaje.attach(part)

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(smtp_user, smtp_pass)

        server.send_message(mensaje)
        server.quit()

        st.success("📧 Reporte diario enviado correctamente")

    except Exception as e:
        st.error(f"Error correo: {e}")

# =========================
# 🔐 SESSION
# =========================
if 'pendiente_registro' not in st.session_state:
    st.session_state.pendiente_registro = False
if 'user' not in st.session_state:
    st.session_state.user = None
if 'justificar' not in st.session_state:
    st.session_state.justificar = False
if 'registro_id' not in st.session_state:
    st.session_state.registro_id = None
if 'modo_kiosco' not in st.session_state:
    st.session_state.modo_kiosco = False
if 'registro_ok' not in st.session_state:
    st.session_state.registro_ok = False
if 'ultimo_movimiento' not in st.session_state:
    st.session_state.ultimo_movimiento = ""
if 'intentos_login' not in st.session_state:
    st.session_state.intentos_login = 0
if 'bloqueado_hasta' not in st.session_state:
    st.session_state.bloqueado_hasta = None

st.set_page_config(layout="wide")

# =========================
# 🔐 LOGIN
# =========================
if not st.session_state.user:

    st.title("🏢 NEOMOTIC Access PRO")

    nombre = st.text_input("Nombre")
    pin = st.text_input("PIN", type="password")

    ahora_utc = datetime.utcnow()
    bloqueado_hasta = st.session_state.bloqueado_hasta
    if bloqueado_hasta and ahora_utc < bloqueado_hasta:
        segundos_restantes = int((bloqueado_hasta - ahora_utc).total_seconds())
        st.error(f"⛔ Demasiados intentos fallidos. Intenta de nuevo en {segundos_restantes} segundos.")
        st.stop()

    if st.button("Ingresar"):
        res = supabase.table("empleados")\
            .select("*")\
            .eq("nombre", nombre)\
            .eq("activo", True)\
            .execute()

        if res.data and validar_pin(res.data[0], pin):
            st.session_state.user = res.data[0]
            st.session_state.intentos_login = 0
            st.session_state.bloqueado_hasta = None
            st.rerun()
        else:
            st.session_state.intentos_login += 1
            if st.session_state.intentos_login >= 5:
                st.session_state.bloqueado_hasta = datetime.utcnow() + timedelta(minutes=5)
                st.session_state.intentos_login = 0
            st.error("❌ Datos incorrectos")


    st.stop()

# =========================
# 👤 USER
# =========================
user = st.session_state.get("user")

if not user:
    st.error("Sesión inválida")
    st.stop()
    
# 🚨 VALIDACIÓN DE SUCURSAL
if not user.get("sucursal_id"):
    st.error("🚫 No tienes sucursal asignada. Contacta a administración.")
    st.stop()
    
# 🔥 FIX ADMIN NO BLOQUEADO
if user.get("rol") in ROLES_ADMIN:
    st.session_state.registro_ok = False

st.title("🏢 NEOMOTIC Access PRO")
st.success(f"👤 {user['nombre']} | {user.get('rol','empleado')}")

# =========================
# 🔘 CONTROLES
# =========================
if st.button("🚪 Cerrar sesión"):
    st.session_state.user = None
    st.rerun()

# 🖥️ CONTROL KIOSCO (MULTI-ROL)
if user.get("rol") in ROLES_KIOSCO:
    st.divider()
    st.subheader("🖥️ Modo Kiosco")

    col1, col2 = st.columns(2)

    if col1.button("🟢 Activar"):
        st.session_state.modo_kiosco = True
        st.rerun()

    if col2.button("🔴 Salir"):
        st.session_state.modo_kiosco = False
        st.rerun()

# =========================
# 🧠 VALIDACIONES
# =========================
def validar_flujo(nombre, tipo):

    df = obtener_registros()

    if df.empty:
        return True, ""

    df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce')
    df = df.dropna(subset=['fecha_hora'])

    hoy = date.today()
    ayer = hoy - timedelta(days=1)

    if tipo == "Salida":
        hoy_regs = df[(df['empleado'] == nombre) & (df['fecha_hora'].dt.date == hoy)]
        if not any(hoy_regs['tipo'] == "Entrada"):
            return False, "⚠️ No puedes registrar SALIDA sin ENTRADA"

    if tipo == "Entrada":
        ayer_regs = df[(df['empleado'] == nombre) & (df['fecha_hora'].dt.date == ayer)]

        if any(ayer_regs['tipo'] == "Entrada") and not any(ayer_regs['tipo'] == "Salida"):
            # 🔥 Obtener el registro de ayer SIN salida
            reg_ayer = ayer_regs[ayer_regs['tipo'] == "Entrada"].iloc[-1]
        
            st.session_state.justificar = True
            st.session_state.registro_id = reg_ayer['id']  # 🔥 AQUÍ LA CLAVE
        
            return True, "⚠️ Falta salida de ayer, se requerirá justificación"

    return True, ""

with st.spinner("📡 Obteniendo ubicación..."):
    time.sleep(1)
    
# =========================
# 📍 REGISTRAR
# =========================
def registrar(nombre, tipo):

    if st.session_state.registro_ok:
        return

    ok, msg = validar_flujo(nombre, tipo)

    if not ok:
        st.error(msg)
        return

    ahora = datetime.now(zona)

    loc = get_geolocation()
    
        # 🚨 CASO 1: No hay respuesta aún
    if loc is None:
        st.info("📡 Solicitando ubicación... acepta el permiso del navegador")
        return

    # 🚨 CASO 2: No viene estructura correcta
    if "coords" not in loc:
        st.warning("⚠️ No se pudo obtener ubicación. Verifica permisos del navegador")
        return

    # ✅ YA TENEMOS GPS
    lat = loc["coords"]["latitude"]
    lon = loc["coords"]["longitude"]

    # 🔒 VALIDAR GEO
    ok_geo, msg_geo = validar_geocerca(lat, lon, user.get('sucursal_id'))

    if not ok_geo:
        st.error(msg_geo)
        return

    est = "A Tiempo"
    min_r = 0

    if tipo == "Entrada":
        h_lim = datetime.strptime(HORA_ENTRADA, "%H:%M:%S").time()
        diff = (datetime.combine(date.today(), ahora.time()) -
                datetime.combine(date.today(), h_lim)).total_seconds() / 60

        min_r = max(0, int(diff))

        if min_r > 30:
            est = "RETARDO CRÍTICO"
        elif min_r > 15:
            est = "Retardo"

    if tipo == "Salida":
        if ahora.time() < datetime.strptime(HORA_SALIDA,"%H:%M:%S").time():
            est = "SALIDA ANTICIPADA"

    try:
        response = supabase.table("registros").insert({
            "empleado": nombre,
            "fecha_hora": ahora.isoformat(),
            "lat": lat,
            "lon": lon,
            "tipo": tipo,
            "estatus": est,
            "min_retardo": min_r,
            "sucursal_id": user['sucursal_id'],
            "justificacion": "",
            "horas_extra": False
        }).execute()

        if response.data:
            st.session_state.registro_id = response.data[0]['id']
            st.session_state.registro_ok = True
            st.session_state.ultimo_movimiento = f"{tipo} registrada"
        
            if est != "A Tiempo":
                st.session_state.justificar = True

            st.toast(f"{tipo} registrada", icon="✅")
            st.rerun()

    except Exception as e:
        st.error(f"❌ Error al insertar: {e}")

# =========================
# 🖥️ KIOSCO QR
# =========================
if st.session_state.modo_kiosco and user.get("rol") in ROLES_KIOSCO:

    st.markdown("# 🏢 RELOJ CHECADOR QR")

    if st.session_state.registro_ok:

        st.success(f"✅ {st.session_state.ultimo_movimiento}")
       
        time.sleep(2)

        st.session_state.registro_ok = False
        st.session_state.ultimo_movimiento = ""

        st.rerun()

    foto = st.camera_input("📷 Escanea QR")

    if foto:
        img = cv2.imdecode(np.asarray(bytearray(foto.getvalue()), dtype=np.uint8), 1)
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)

        if data:
            st.success(f"👤 {data}")

            c1, c2 = st.columns(2)

            if c1.button("📥 ENTRADA"):
                registrar(data, "Entrada")

            if c2.button("📤 SALIDA"):
                registrar(data, "Salida")

    st.stop()

# =========================
# 🧾 NORMAL
# =========================
st.markdown("## 🕒 Reloj Checador")

if st.session_state.registro_ok and user.get("rol") not in ROLES_ADMIN:
    st.success(f"✅ {st.session_state.ultimo_movimiento}")
else:
    c1, c2 = st.columns(2)

    if c1.button("📥 ENTRADA"):
        registrar(user['nombre'], "Entrada")

    if c2.button("📤 SALIDA"):
        registrar(user['nombre'], "Salida")

# =========================
# ⚠️ JUSTIFICACIÓN
# =========================
if st.session_state.justificar:
    st.divider()
    st.warning("⚠️ Se requiere justificación por el estatus del registro")

    with st.form("just"):
        motivo = st.text_area("Escribe el motivo:")

        if st.form_submit_button("Guardar Justificación"):
            if len(motivo) > 5:
                try:
                     supabase.table("registros").update({
                            "justificacion": motivo
                     }).eq("id", st.session_state.registro_id).execute()

                     st.success("✅ Justificación guardada correctamente")
                    
                     # Limpiamos el estado para que desaparezca el formulario
                     st.session_state.justificar = False
                     st.session_state.pendiente_registro = True

                     st.rerun()
                
                except Exception as e:
                    st.error(f"Error al actualizar en Supabase: {e}")
            else:
                st.error("Por favor, escribe un motivo más detallado (mínimo 6 caracteres).")
                
# =========================
# 🔥 REGISTRO POST-JUSTIFICACIÓN
# =========================
if st.session_state.get("pendiente_registro"):
    st.session_state.pendiente_registro = False
    registrar(user['nombre'], "Entrada")

# =========================
# 📊 DASHBOARD SOLO ADMIN
# =========================
if user.get("rol") in ROLES_ADMIN:

    st.divider()
    st.subheader("📊 Dashboard Ejecutivo")

    df = obtener_registros()
    hoy = pd.DataFrame()

    if not df.empty:

        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce')
        df = df.dropna(subset=['fecha_hora'])

        hoy = df[df['fecha_hora'].dt.date == datetime.now().date()]

        c1, c2, c3 = st.columns(3)
        c1.metric("Registros hoy", len(hoy))
        c2.metric("Retardos", len(hoy[hoy['estatus'].str.contains("Retardo", na=False)]))
        c3.metric("Salidas anticipadas", len(hoy[hoy['estatus']=="SALIDA ANTICIPADA"]))

        st.dataframe(hoy.sort_values("fecha_hora", ascending=False))

        st.subheader("📈 Tendencia")
        df['dia'] = df['fecha_hora'].dt.date
        
        st.subheader("📊 Análisis visual")

        df['dia'] = df['fecha_hora'].dt.date

        col1, col2 = st.columns(2)
        
        # 📊 Registros por día
        fig1 = px.bar(
            df.groupby('dia').size().reset_index(name='registros'),
            x='dia',
            y='registros',
            title="Registros por día"
        )
        
        col1.plotly_chart(fig1, use_container_width=True)
        
        # 📊 Retardos por empleado
        fig2 = px.bar(
            df.groupby('empleado')['min_retardo'].sum().reset_index(),
            x='empleado',
            y='min_retardo',
            title="Minutos de retardo por empleado"
        )
        
        col2.plotly_chart(fig2, use_container_width=True)


        st.subheader("🗺️ Ubicaciones")
        pts = hoy.dropna(subset=['lat','lon'])
        if not pts.empty:
            st.map(pts)

        empleados = obtener_empleados()
        presentes = hoy['empleado'].unique()

        faltantes = [e['nombre'] for e in empleados if e['nombre'] not in presentes]

        st.subheader("🚫 Faltantes")
        for f in faltantes:
            st.error(f)
        
        ahora = datetime.now(zona)
        hora_actual = ahora.strftime("%H:%M")
        fecha_hoy = ahora.date()

        if hora_actual == "19:15":
            if st.session_state.get("fecha_reporte") != fecha_hoy:
                enviar_reporte_diario(hoy)
                st.session_state.fecha_reporte = fecha_hoy

    # =========================
    # 🧾 EXPORTAR
    # =========================
    st.subheader("🧾 Exportar datos")
    exportar_excel(df)
    
    # 📧 BOTÓN DE ALERTA
    if st.button("📧 Enviar reporte diario"):
        enviar_reporte_diario(hoy)


if user.get("rol") in ROLES_ADMIN:
    # =========================
    # 📦 GENERAR QR MASIVO (ADMIN)
    # =========================
    st.divider()
    st.subheader("📦 Generar QR de empleados")

    empleados = obtener_empleados()

    if empleados:

        nombres_emp = [e['nombre'] for e in empleados]

        st.info(f"Total empleados: {len(nombres_emp)}")

        col1, col2 = st.columns(2)

        # =========================
        # 🔹 DESCARGAR TODOS (ZIP)
        # =========================
        if col1.button("📦 Descargar todos los QR (ZIP)"):

            zip_buffer = BytesIO()

            with zipfile.ZipFile(zip_buffer, "w") as z:
                for emp in empleados:
                    qr = qrcode.make(emp['nombre'])

                    img_bytes = BytesIO()
                    qr.save(img_bytes, format='PNG')

                    z.writestr(f"{emp['nombre']}.png", img_bytes.getvalue())

            st.download_button(
                "⬇️ Descargar ZIP",
                zip_buffer.getvalue(),
                file_name="QR_Empleados.zip",
                mime="application/zip"
            )

        # =========================
        # 🔹 QR INDIVIDUAL
        # =========================
        emp_sel = col2.selectbox("Selecciona empleado", nombres_emp)

        if emp_sel:
            qr = qrcode.make(emp_sel)
            img_bytes = BytesIO()
            qr.save(img_bytes, format='PNG')
            img_bytes.seek(0)

            st.image(img_bytes, caption=f"QR de {emp_sel}")

            img_bytes = BytesIO()
            qr.save(img_bytes, format='PNG')
            img_bytes.seek(0)

            st.download_button(
                "⬇️ Descargar QR individual",
                img_bytes.getvalue(),
                file_name=f"{emp_sel}.png",
                mime="image/png"
            )

    else:
        st.warning("No hay empleados registrados")


