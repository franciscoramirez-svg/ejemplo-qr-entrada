import streamlit as st
from core.biometria import guardar_foto_empleado, reconocer_empleado, obtener_empleados_biometria, FACE_RECOGNITION_AVAILABLE
from services.data import obtener_empleados


def render_biometria_captura():
    """Interfaz para capturar y almacenar fotos de empleados."""
    st.markdown("## 📸 Captura biométrica de empleados")
    
    if not FACE_RECOGNITION_AVAILABLE:
        st.error("⚠️ Biblioteca face_recognition no instalada. Instala con: pip install face-recognition")
        return
    
    st.info("Captura fotos de empleados para crear su perfil biométrico.")
    
    empleados = obtener_empleados()
    opciones = [e.get("nombre") for e in empleados if e.get("nombre")]
    
    if not opciones:
        st.warning("No hay empleados disponibles.")
        return
    
    nombre = st.selectbox("Selecciona empleado", opciones)
    empleado_sel = next((e for e in empleados if e.get("nombre") == nombre), None)
    
    if not empleado_sel:
        st.error("Empleado no encontrado.")
        return
    
    foto = st.camera_input("📷 Captura tu rostro", key="cap_biometria")
    
    if foto:
        st.image(foto, caption="Foto capturada", use_column_width=True)
        
        if st.button("Guardar perfil biométrico"):
            imagen_bytes = foto.getvalue()
            success, message = guardar_foto_empleado(
                empleado_sel["id"],
                nombre,
                imagen_bytes
            )
            
            if success:
                st.success(f"✅ {message}")
            else:
                st.error(f"❌ {message}")


def render_biometria_login():
    """Interfaz de login biométrico con reconocimiento."""
    st.markdown("## 🔒 Acceso biométrico")
    
    if not FACE_RECOGNITION_AVAILABLE:
        st.warning("Biometría no disponible. Usa Nombre + PIN.")
        return None
    
    st.info("Captura tu rostro para iniciar sesión automáticamente.")
    
    foto = st.camera_input("📷 Captura tu rostro")
    
    if foto:
        st.image(foto, caption="Rostro capturado", use_column_width=True)
        
        with st.spinner("🔍 Reconociendo rostro..."):
            imagen_bytes = foto.getvalue()
            nombre_encontrado, empleado_id = reconocer_empleado(imagen_bytes)
        
        if nombre_encontrado:
            st.success(f"✅ ¡Bienvenido {nombre_encontrado}!")
            return nombre_encontrado
        else:
            st.error("❌ No se pudo reconocer. Intenta de nuevo o usa otro método.")
            if st.button("Usar PIN manual"):
                st.session_state["login_method"] = "Nombre + PIN"
                st.rerun()
    
    return None
