import streamlit as st
from datetime import datetime
import pytz
from services.supabase_client import get_supabase
from services.data import obtener_sucursal_por_id, obtener_empleados
from core.attendance import validar_pin, cerrar_entradas_abiertas_anteriores, contar_faltas_semana
from core.biometria import reconocer_empleado, FACE_RECOGNITION_AVAILABLE
from config import ZONA

supabase = get_supabase()


def _style_login():
    st.markdown(
        """
        <style>
        .login-hero {
            background: linear-gradient(135deg, #0f172a 0%, #08122c 45%, #0b1125 100%);
            color: white;
            border-radius: 24px;
            padding: 32px;
            box-shadow: 0 25px 80px rgba(0, 0, 0, 0.25);
            margin-bottom: 24px;
        }
        .login-hero h1 {
            font-size: 3rem;
            margin-bottom: 0.4rem;
            letter-spacing: 0.2rem;
        }
        .login-hero .subtitle {
            color: #a5b4fc;
            font-size: 1.05rem;
            margin-bottom: 1.6rem;
        }
        .login-card {
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 24px;
            padding: 28px;
            margin-bottom: 24px;
        }
        .login-card label {
            color: #e2e8f0;
        }
        .login-card .small-note {
            color: #cbd5e1;
            font-size: 0.92rem;
        }
        .ui-button {
            border-radius: 16px;
            font-size: 1rem;
            padding: 0.95rem 1.2rem;
            width: 100%;
        }
        .welcome-badge {
            display: inline-block;
            border-radius: 999px;
            background: rgba(59, 130, 246, 0.15);
            color: #93c5fd;
            padding: 7px 16px;
            margin-bottom: 16px;
            font-weight: 500;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_splash_screen():
    _style_login()
    st.markdown(
        """
        <div class='login-hero'>
            <div class='welcome-badge'>BIENVENIDO A NEOACCESS PRO</div>
            <h1>Tu control de asistencia futurista</h1>
            <p class='subtitle'>Acceso seguro, geolocalizado y listo para tu sucursal. Registra entradas, salidas y mantiene a tus equipos alineados.</p>
            <p class='small-note'>Próxima fase: biometría y autenticación multimodal.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("""
        <div class='login-card'>
            <h2>Comienza ya</h2>
            <p class='small-note'>Pulsa LET'S GO! para ingresar al sistema. Actualmente el acceso es mediante nombre y PIN. Más adelante puedes integrar reconocimiento facial Liveness.</p>
        </div>
    """, unsafe_allow_html=True)

    if st.button("LET'S GO!", key="lets_go"):
        st.session_state.app_stage = "login"
        st.rerun()


def authenticate(nombre, pin):
    try:
        res = supabase.table("empleados").select(
            "id,nombre,rol,activo,sucursal_id,pin,pin_hash,hora_entrada,hora_salida"
        ).eq("nombre", nombre).eq("activo", True).execute()
    except Exception as exc:
        return None, f"Error de conexión con Supabase: {exc}"

    if not getattr(res, "data", None):
        return None, "Usuario no encontrado o inactivo"

    empleado = res.data[0]
    if not validar_pin(empleado, pin):
        return None, "PIN incorrecto"
    if not empleado.get("sucursal_id"):
        return None, "Usuario sin sucursal asignado"

    suc = obtener_sucursal_por_id(empleado["sucursal_id"])
    if not suc:
        return None, "Sucursal asignada no existe"

    cierre_automatico = cerrar_entradas_abiertas_anteriores(empleado["nombre"], ZONA)
    faltas = contar_faltas_semana(empleado["nombre"], datetime.now(ZONA).date())
    if faltas >= 3:
        return None, f"Tienes {faltas} faltas esta semana. Consulta a tu supervisor."

    user = {
        "id": empleado["id"],
        "nombre": empleado["nombre"],
        "rol": empleado.get("rol", "empleado"),
        "sucursal_id": str(empleado["sucursal_id"]),
        "sucursal_nombre": suc.get("nombre", "Sucursal"),
        "hora_entrada": empleado.get("hora_entrada"),
        "hora_salida": empleado.get("hora_salida"),
        "faltas_semana": faltas,
        "cierre_automatico": cierre_automatico,
    }
    return user, None


def render_login_method_selection():
    methods = [
        "Nombre + PIN",
        "PIN rápido",
        "Biometría (próximamente)",
    ]
    current = st.session_state.get("login_method", methods[0])
    if current not in methods:
        current = methods[0]
    method = st.selectbox("Método de acceso", methods, index=methods.index(current))
    st.session_state["login_method"] = method
    return method


def render_login_form():
    _style_login()
    st.markdown(
        """
        <div class='login-card'>
            <h2>Inicia sesión</h2>
            <p class='small-note'>El registro sólo funciona desde sucursales autorizadas con geolocalización activa.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    login_method = render_login_method_selection()
    st.markdown("---")

    if login_method == "Biometría (próximamente)":
        if not FACE_RECOGNITION_AVAILABLE:
            st.warning("📦 Biometría no disponible. Instala: pip install face-recognition")
            return
            
        st.info("Coloca tu rostro frente a la cámara para identificarte automáticamente.")
        
        # Usamos una key única para la cámara del login
        foto = st.camera_input("📷 Escaneo Facial", key="cam_login_biometrico")
        
        if foto:
            with st.spinner("🔍 Buscando coincidencia en la base de datos..."):
                imagen_bytes = foto.getvalue()
                # Llamamos a la función de core/biometria.py que ya tienes
                nombre_encontrado, empleado_id = reconocer_empleado(imagen_bytes, umbral_tolerancia=0.5)
                
                if nombre_encontrado:
                    st.success(f"✅ ¡Rostro reconocido: {nombre_encontrado}!")
                    st.session_state["biometric_user"] = nombre_encontrado
                    st.session_state["biometric_ready"] = True
                    # Emitir un sonido de éxito (opcional)
                    st.toast(f"Bienvenido {nombre_encontrado}", icon="👤")
                else:
                    st.error("❌ No se encontró ningún empleado que coincida. Intenta de nuevo o usa PIN.")
                    st.session_state["biometric_ready"] = False

        # Si el rostro fue reconocido, pedimos el PIN de confirmación
        if st.session_state.get("biometric_ready") and st.session_state.get("biometric_user"):
            with st.form("login_biometric_form"):
                st.markdown(f"**Confirmación de Seguridad para: {st.session_state['biometric_user']}**")
                pin = st.text_input("PIN de confirmación", type="password", placeholder="Ingresa tu PIN")
                submit = st.form_submit_button("Acceder al Sistema")
                
                if submit:
                    if not pin:
                        st.error("Ingresa tu PIN para continuar")
                    else:
                        nombre = st.session_state["biometric_user"]
                        user, error = authenticate(nombre.strip(), pin.strip())
                        if error:
                            st.error(error)
                            # Si el PIN falla, reseteamos para seguridad
                            st.session_state["biometric_ready"] = False
                        else:
                            # LOGIN EXITOSO
                            st.session_state.user = user
                            st.session_state.app_stage = "app"
                            # Limpiar estados biométricos
                            st.session_state["biometric_ready"] = False
                            st.session_state["biometric_user"] = None
                            st.rerun()

    # Inicialización limpia de variables para los siguientes métodos
    nombre, pin, user, error = "", "", None, None
    submit = False

    if login_method == "PIN rápido":
        empleados = obtener_empleados()
        opciones = [e.get("nombre") for e in empleados if e.get("nombre")]
        if opciones:
            nombre = st.selectbox("Empleado", opciones)
            empleado_sel = next((e for e in empleados if e.get("nombre") == nombre), None)
        else:
            st.warning("No hay empleados disponibles para PIN rápido.")
            empleado_sel = None

        if empleado_sel and empleado_sel.get("pin"):
            if st.button("Autocompletar PIN"):
                st.session_state["login_auto_pin"] = str(empleado_sel.get("pin"))
                st.rerun()
        elif empleado_sel:
            st.info("PIN automático no disponible para este empleado. Ingresa el PIN manualmente.")

        with st.form("login_form"):
            pin = st.text_input("PIN", type="password", value=st.session_state.get("login_auto_pin", ""), placeholder="Ingresa tu PIN")
            submit = st.form_submit_button("Entrar")
    else:
        with st.form("login_form"):
            nombre = st.text_input("Nombre", placeholder="Ejemplo: Juan Pérez")
            pin = st.text_input("PIN", type="password", placeholder="Ingresa tu PIN", value=st.session_state.get("login_auto_pin", "") if login_method == "Nombre + PIN" else "")
            submit = st.form_submit_button("Entrar")

    if submit:
        if not nombre or not pin:
            st.error("Escribe tu nombre y PIN para continuar")
            return

        user, error = authenticate(nombre.strip(), pin.strip())
        if error:
            st.error(error)
            return

        st.session_state.user = user
        st.session_state.app_stage = "app"
        st.session_state.last_action = None
        st.session_state.action_message = None
        st.session_state.registro_ok = False
        st.session_state.registro_id_justificar = None
        st.session_state.registro_pendiente = None
        st.session_state.login_auto_pin = None
        st.session_state.biometric_ready = False
        st.session_state.modo_kiosco = False
        st.rerun()

    st.markdown("---")
    st.info("Nota: más adelante se puede integrar reconocimiento facial Liveness y mayor seguridad biométrica.")
