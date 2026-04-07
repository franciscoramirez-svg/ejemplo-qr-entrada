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
import plotly.graph_objects as go
import time
import hashlib
import hmac
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import streamlit.components.v1 as components

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

def obtener_sucursales_catalogo():
    data = supabase.table("sucursales").select("id,nombre").execute().data
    df = pd.DataFrame(data if data else [])
    if df.empty:
        return df
    df["id"] = df["id"].astype(str)
    return df

def enriquecer_con_nombre_sucursal(df):
    if df.empty or "sucursal_id" not in df.columns:
        return df
    cat = obtener_sucursales_catalogo()
    if cat.empty:
        return df
    out = df.copy()
    out["sucursal_id"] = out["sucursal_id"].astype(str)
    out = out.merge(cat.rename(columns={"id": "sucursal_id", "nombre": "sucursal_nombre"}), on="sucursal_id", how="left")
    return out

def obtener_timezone_sucursal(sucursal_id):
    try:
        suc = supabase.table("sucursales").select("timezone").eq("id", sucursal_id).execute().data
        if suc and suc[0].get("timezone"):
            return str(suc[0]["timezone"])
    except Exception:
        pass
    return "America/Mexico_City"

def existe_registro_duplicado(nombre, tipo, ahora, ventana_min=2):
    """
    Evita doble click o reintentos involuntarios:
    no permite mismo tipo para el mismo empleado dentro de una ventana corta.
    """
    df = obtener_registros()
    if df.empty:
        return False

    df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce')
    df = df.dropna(subset=['fecha_hora'])
    if df.empty:
        return False

    hoy = ahora.date()
    cand = df[
        (df['empleado'] == nombre) &
        (df['tipo'] == tipo) &
        (df['fecha_hora'].dt.date == hoy)
    ]
    if cand.empty:
        return False

    ultimo = cand.sort_values('fecha_hora').iloc[-1]['fecha_hora']
    if hasattr(ultimo, "tzinfo") and ultimo.tzinfo is not None:
        ultimo = ultimo.tz_convert(zona).to_pydatetime().replace(tzinfo=None)
    else:
        ultimo = pd.Timestamp(ultimo).to_pydatetime()

    delta_min = abs((ahora.replace(tzinfo=None) - ultimo).total_seconds() / 60)
    return delta_min <= ventana_min

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
def exportar_excel(df, file_name="reporte_asistencia.xlsx"):

    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    st.download_button(
        "⬇️ Descargar Excel",
        data=output.getvalue(),
        file_name=file_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# =========================
# 📧 EMAIL
# =========================
def enviar_reporte_diario(df_hoy):

    if df_hoy.empty:
        st.warning("No hay registros hoy")
        return
        
    df_hoy = enriquecer_con_nombre_sucursal(df_hoy)    

    # 📊 Excel de HOY + pestañas por sucursal
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_hoy.to_excel(writer, index=False, sheet_name="Resumen")
        if "sucursal_id" in df_hoy.columns:
            for suc_id, grp in df_hoy.groupby("sucursal_id", dropna=False):
                suc_nombre = str(grp["sucursal_nombre"].iloc[0]) if "sucursal_nombre" in grp.columns and pd.notna(grp["sucursal_nombre"].iloc[0]) else f"Suc_{suc_id}"
                hoja = suc_nombre[:31]
                grp.to_excel(writer, index=False, sheet_name=hoja)
    output.seek(0)

    hoy_str = datetime.now(zona).strftime("%Y-%m-%d")

    mensaje = MIMEMultipart()
    mensaje['Subject'] = f"📊 Reporte Diario de Asistencia - {hoy_str}"
    smtp_user = st.secrets.get("SMTP_USER")
    smtp_pass = st.secrets.get("SMTP_PASSWORD")
    email_to = st.secrets.get("REPORTE_DIARIO_TO")
    email_cc_raw = st.secrets.get("REPORTE_DIARIO_CC", "")

    cc_list = [x.strip() for x in str(email_cc_raw).split(",") if x.strip()]

    if not smtp_user or not smtp_pass or not email_to:
        st.error("Faltan credenciales de correo en secrets: SMTP_USER, SMTP_PASSWORD, REPORTE_DIARIO_TO")
        return

    mensaje['From'] = smtp_user
    mensaje['To'] = email_to
    mensaje['Cc'] = ", ".join(cc_list)

    retardos = len(df_hoy[df_hoy['estatus'].str.contains("Retardo|CRÍTICO", case=False, na=False)])
    faltas = 0
    try:
        empleados = obtener_empleados()
        presentes = set(df_hoy['empleado'].dropna().unique())
        faltas = len([e for e in empleados if e.get('nombre') not in presentes])
    except Exception:
        faltas = 0
    total_registros = len(df_hoy)
    detalle_sucursal = ""
    if "sucursal_id" in df_hoy.columns:
        if "sucursal_nombre" in df_hoy.columns:
            corte = df_hoy.groupby("sucursal_nombre").size().reset_index(name="registros")
            detalle_sucursal = "\n".join(
                [f"• {row['sucursal_nombre']}: {row['registros']} registros" for _, row in corte.iterrows()]
            )
        else:
            corte = df_hoy.groupby("sucursal_id").size().reset_index(name="registros")
            detalle_sucursal = "\n".join(
                [f"• Sucursal {row['sucursal_id']}: {row['registros']} registros" for _, row in corte.iterrows()]
            )
    
    mensaje.attach(MIMEText("Buena tarde,\n\n"
                            "Se adjunta el reporte diario de asistencia." 
                            f" Resumen del día:\n\n"
                            f"📝 Total registros: {total_registros}\n"
                            f"⏰ Retardos: {retardos}\n"
                            f"🚫 Faltantes: {faltas}\n"
                            f"\n"
                            f"📍 Detalle por sucursal:\n{detalle_sucursal if detalle_sucursal else 'Sin dato de sucursal'}\n"
                            f"\n"
                            f"Sistema neoACCESS PRO"
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
        server.login(smtp_user, smtp_pass)  # tibhlarouqepjzpu

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
if 'ultima_geo' not in st.session_state:
    st.session_state.ultima_geo = None
if 'requiere_registro_post_justificacion' not in st.session_state:
    st.session_state.requiere_registro_post_justificacion = False
if 'ultimo_reporte_status' not in st.session_state:
    st.session_state.ultimo_reporte_status = "Sin envío hoy"
if 'ultimo_reporte_hora' not in st.session_state:
    st.session_state.ultimo_reporte_hora = None

st.set_page_config(layout="wide")

# =========================
# 🔐 LOGIN
# =========================
if not st.session_state.user:

    st.title("🏢 neoAccess PRO")

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
    st.error("🚫 No tienes sucursal asignada. Contacta a administración/Supervisor.")
    st.stop()

tz_sucursal_str = obtener_timezone_sucursal(user.get("sucursal_id"))
try:
    zona_usuario = pytz.timezone(tz_sucursal_str)
except Exception:
    tz_sucursal_str = "America/Mexico_City"
    zona_usuario = pytz.timezone(tz_sucursal_str)
    
# 🔥 FIX ADMIN NO BLOQUEADO
if user.get("rol") in ROLES_ADMIN:
    st.session_state.registro_ok = False

st.title("🏢 neoAccess PRO")
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

    hoy = datetime.now(zona_usuario).date()
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
            st.session_state.requiere_registro_post_justificacion = True
        
            return True, "⚠️ Falta salida de ayer, se requerirá justificación"

    return True, ""

with st.spinner("📡 Obteniendo ubicación..."):
    time.sleep(1)

# Intentamos obtener GPS en cada render y lo guardamos para usarlo al registrar.
geo_actual = get_geolocation()
if geo_actual and "coords" in geo_actual:
    st.session_state.ultima_geo = geo_actual
    
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

    ahora = datetime.now(zona_usuario)

    loc = st.session_state.get("ultima_geo")
    
    # 🚨 CASO 1: No hay respuesta aún
    if loc is None:
        st.info("📡 No tenemos tu ubicación todavía. Acepta el permiso del navegador y vuelve a presionar.")
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
        diff = (datetime.combine(ahora.date(), ahora.time()) -
                datetime.combine(ahora.date(), h_lim)).total_seconds() / 60

        min_r = max(0, int(diff))

        if min_r > 30:
            est = "RETARDO CRÍTICO"
        elif min_r > 15:
            est = "Retardo"

    if tipo == "Salida":
        if ahora.time() < datetime.strptime(HORA_SALIDA,"%H:%M:%S").time():
            est = "SALIDA ANTICIPADA"

    if existe_registro_duplicado(nombre, tipo, ahora, ventana_min=2):
        st.warning(f"⚠️ Ya existe un registro de {tipo} en los últimos 2 minutos. Evitamos duplicado.")
        return

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
                st.session_state.requiere_registro_post_justificacion = False

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

components.html(f"""
<div style="font-family: 'Orbitron', sans-serif; background:#0d1117; color:#00E5FF;
padding:12px 18px; border-radius:12px; border:1px solid #00E5FF; text-align:center;
box-shadow: 0 0 18px rgba(0,229,255,.35); margin-bottom:12px;">
  <div style="font-size:13px; opacity:.8;">Hora actual (MX)</div>
  <div id="neoClock" style="font-size:34px; font-weight:700; letter-spacing:2px;">--:--:--</div>
</div>
<script>
function tick(){{
  const now = new Date();
  const fmt = now.toLocaleTimeString('es-MX', {{hour12:false,timeZone:'{tz_sucursal_str}'}});
  document.getElementById('neoClock').innerText = fmt;
}}
setInterval(tick, 1000); tick();
</script>
""", height=110)
if st.session_state.get("ultima_geo") and "coords" in st.session_state.ultima_geo:
    st.caption(
        f"📍 GPS detectado: "
        f"{st.session_state.ultima_geo['coords']['latitude']:.6f}, "
        f"{st.session_state.ultima_geo['coords']['longitude']:.6f}"
    )
else:
    st.caption("📍 GPS pendiente: permite ubicación en el navegador para poder registrar.")

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
                     st.session_state.pendiente_registro = st.session_state.get("requiere_registro_post_justificacion", False)
                     st.session_state.requiere_registro_post_justificacion = False

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
    st.subheader("📊 NeoDashboard")

    df = obtener_registros()
    hoy = pd.DataFrame()

    if not df.empty:

        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'], errors='coerce')
        df = df.dropna(subset=['fecha_hora'])

        hoy = df[df['fecha_hora'].dt.date == datetime.now(zona_usuario).date()]

        c1, c2, c3 = st.columns(3)
        c1.metric("Registros hoy", len(hoy))
        c2.metric("Retardos", len(hoy[hoy['estatus'].str.contains("Retardo|CRÍTICO", case=False, na=False)]))
        c3.metric("Salidas anticipadas", len(hoy[hoy['estatus']=="SALIDA ANTICIPADA"]))
        c4, c5, c6 = st.columns(3)
        empleados_hoy = hoy['empleado'].nunique() if 'empleado' in hoy.columns else 0
        total_empleados = len(obtener_empleados())
        puntual = len(hoy[hoy['estatus'] == "A Tiempo"])
        puntualidad_pct = (puntual / len(hoy) * 100) if len(hoy) else 0
        cobertura_pct = (empleados_hoy / total_empleados * 100) if total_empleados else 0
          # Fallback robusto por si se reordena UI y alguna variable queda fuera de alcance.
        presentes = hoy['empleado'].unique()
        try:
            empleados_ref = empleados
        except NameError:
            empleados_ref = obtener_empleados()
        try:
            presentes_ref = set(presentes)
        except NameError:
            presentes_ref = set()
        faltantes = [e.get('nombre')
            for e in (empleados_ref or [])
            if e.get('nombre') and e.get('nombre') not in presentes_ref
        ]
        c4.metric("Puntualidad", f"{puntualidad_pct:.1f}%")
        c5.metric("Cobertura (presentes/empleados)", f"{cobertura_pct:.1f}%")
        c6.metric("Faltantes hoy", len(faltantes))

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
            sucursales = pd.DataFrame(supabase.table("sucursales").select("id,lat,lon,nombre").execute().data)
            if not sucursales.empty:
                pts_map = pts[['lat', 'lon']].copy()
                pts_map['etiqueta'] = pts.get('empleado', 'Registro')
                pts_map['tipo_punto'] = 'Registro'

                suc_map = sucursales[['lat', 'lon']].copy()
                suc_map['etiqueta'] = sucursales.get('nombre', sucursales['id']).astype(str)
                suc_map['tipo_punto'] = 'Sucursal'

                mix = pd.concat([pts_map, suc_map], ignore_index=True)

                fig_map = px.scatter_map(
                    mix,
                    lat='lat',
                    lon='lon',
                    color='tipo_punto',
                    hover_name='etiqueta',
                    zoom=4,
                    height=420,
                    color_discrete_map={'Registro': '#00BFFF', 'Sucursal': 'red'}
                )
                fig_map.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 0})
                st.plotly_chart(fig_map, use_container_width=True)
            else:
                st.map(pts)
        else:
            ultimos = df.dropna(subset=['lat', 'lon']).sort_values("fecha_hora", ascending=False).head(200)
            if not ultimos.empty:
                st.info("No hay ubicaciones para hoy; mostrando registros más recientes.")
                st.map(ultimos[['lat', 'lon']])
            else:
                st.info("No hay coordenadas registradas todavía.")

        
        st.subheader("🚫 Faltantes")
        for f in faltantes:
            st.error(f)
        
        ahora = datetime.now(zona_usuario)
        hora_actual = ahora.strftime("%H:%M")
        fecha_hoy = ahora.date()
        hora_objetivo = datetime.strptime("19:15", "%H:%M").time()
        if ahora.time() >= hora_objetivo and st.session_state.get("fecha_reporte") != fecha_hoy:
             ok_mail, hora_mail = enviar_reporte_diario(hoy)
             st.session_state.fecha_reporte = fecha_hoy
             st.session_state.ultimo_reporte_status = "✅ Enviado" if ok_mail else "❌ Error al enviar"
             st.session_state.ultimo_reporte_hora = hora_mail.strftime("%Y-%m-%d %H:%M:%S") if hora_mail else None

    # =========================
    # 🧾 EXPORTAR
    # =========================
    st.subheader("🧾 Exportar datos")
    if not df.empty:
        min_fecha = df['fecha_hora'].dt.date.min()
        max_fecha = df['fecha_hora'].dt.date.max()
        col_f1, col_f2 = st.columns(2)
        fecha_inicio = col_f1.date_input(
            "Fecha inicio",
            value=max_fecha,
            min_value=min_fecha,
            max_value=max_fecha,
            key="fecha_inicio_export_admin"
        )
        fecha_fin = col_f2.date_input(
            "Fecha fin",
            value=max_fecha,
            min_value=min_fecha,
            max_value=max_fecha,
            key="fecha_fin_export_admin"
        )

        if fecha_inicio > fecha_fin:
            st.warning("La fecha inicio no puede ser mayor que la fecha fin.")
            fecha_inicio, fecha_fin = fecha_fin, fecha_inicio

        sucursales_cat = obtener_sucursales_catalogo()
        opciones_sucursal = ["Todas"] + (sucursales_cat["nombre"].dropna().tolist() if not sucursales_cat.empty else [])
        sucursal_sel = st.selectbox("Sucursal a exportar", opciones_sucursal, key="sucursal_export_admin")

        mask_rango = (df['fecha_hora'].dt.date >= fecha_inicio) & (df['fecha_hora'].dt.date <= fecha_fin)
        df_export = df[mask_rango].copy()
        df_export = enriquecer_con_nombre_sucursal(df_export)
        if sucursal_sel != "Todas" and "sucursal_nombre" in df_export.columns:
            df_export = df_export[df_export["sucursal_nombre"] == sucursal_sel]

        st.caption(f"Registros para exportar ({fecha_inicio} a {fecha_fin}, {sucursal_sel}): {len(df_export)}")
        exportar_excel(df_export, file_name=f"reporte_asistencia_{fecha_inicio}_a_{fecha_fin}.xlsx")
    else:
        st.info("No hay datos para exportar todavía.")
    
    # 📧 BOTÓN DE ALERTA
    if st.button("📧 Enviar reporte diario"):
        ok_mail, hora_mail = enviar_reporte_diario(hoy)
        st.session_state.ultimo_reporte_status = "✅ Enviado manual" if ok_mail else "❌ Error al enviar manual"
        st.session_state.ultimo_reporte_hora = hora_mail.strftime("%Y-%m-%d %H:%M:%S") if hora_mail else None

    st.info(
        f"Estado correo automático/manual: {st.session_state.get('ultimo_reporte_status', 'Sin envío')}"
        + (f" | Hora: {st.session_state.get('ultimo_reporte_hora')}" if st.session_state.get("ultimo_reporte_hora") else "")
    )

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
        
