import numpy as np
import cv2
from io import BytesIO
import json
import hashlib
from datetime import datetime
from services.supabase_client import get_supabase

supabase = get_supabase()

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False


def generar_embedding_facial(imagen_bytes):
    """
    Genera un embedding (vector de características) de un rostro.
    
    Args:
        imagen_bytes: Bytes de la imagen capturada
    
    Returns:
        embedding (list) o None si no se detectó rostro
    """
    if not FACE_RECOGNITION_AVAILABLE:
        return None
    
    try:
        nparr = np.frombuffer(imagen_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb_img, model="hog")
        
        if not face_locations:
            return None
        
        face_encodings = face_recognition.face_encodings(rgb_img, face_locations)
        if face_encodings:
            return face_encodings[0].tolist()
        return None
    except Exception as e:
        print(f"Error generando embedding: {e}")
        return None


def guardar_foto_empleado(empleado_id, nombre, imagen_bytes):
    """
    Guarda la foto y embedding de un empleado en Supabase.
    
    Args:
        empleado_id: ID del empleado
        nombre: Nombre del empleado
        imagen_bytes: Bytes de la foto
    
    Returns:
        success (bool), message (str)
    """
    try:
        embedding = generar_embedding_facial(imagen_bytes)
        if embedding is None:
            return False, "No se detectó rostro en la imagen"
        
        timestamp = datetime.now().isoformat()
        data = {
            "empleado_id": str(empleado_id),
            "nombre": nombre,
            "embedding": json.dumps(embedding),
            "fecha_captura": timestamp,
            "hash_imagen": hashlib.md5(imagen_bytes).hexdigest(),
        }
        
        res = supabase.table("biometria_empleados").insert(data).execute()
        if getattr(res, "error", None) is not None:
            return False, f"Error al guardar: {res.error}"
        
        return True, "Foto de empleado guardada correctamente"
    except Exception as e:
        return False, f"Error: {e}"


def reconocer_empleado(imagen_bytes, umbral_tolerancia=0.6):
    """
    Reconoce un empleado comparando su rostro con la base de datos.
    
    Args:
        imagen_bytes: Bytes de la imagen capturada
        umbral_tolerancia: Umbral de similitud (0-1, menor es más estricto)
    
    Returns:
        (empleado_nombre, empleado_id) o (None, None)
    """
    try:
        embedding_capturado = generar_embedding_facial(imagen_bytes)
        if embedding_capturado is None:
            return None, None
        
        res = supabase.table("biometria_empleados").select("nombre, empleado_id, embedding").execute()
        if not getattr(res, "data", None):
            return None, None
        
        mejor_match = None
        mejor_distancia = float('inf')
        
        for registro in res.data:
            embedding_almacenado = json.loads(registro["embedding"])
            embedding_almacenado = np.array(embedding_almacenado)
            embedding_capturado_arr = np.array(embedding_capturado)
            
            distancia = np.linalg.norm(embedding_capturado_arr - embedding_almacenado)
            
            if distancia < mejor_distancia:
                mejor_distancia = distancia
                mejor_match = registro
        
        if mejor_distancia < umbral_tolerancia:
            return mejor_match["nombre"], mejor_match["empleado_id"]
        
        return None, None
    except Exception as e:
        print(f"Error en reconocimiento: {e}")
        return None, None


def obtener_empleados_biometria():
    """Obtiene lista de empleados que tienen biometría registrada."""
    try:
        res = supabase.table("biometria_empleados").select("distinct nombre, empleado_id").execute()
        return res.data or []
    except Exception:
        return []
