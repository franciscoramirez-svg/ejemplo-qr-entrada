import streamlit as st

try:
    from supabase import create_client
except ImportError as exc:
    create_client = None
    _SUPABASE_IMPORT_ERROR = exc
else:
    _SUPABASE_IMPORT_ERROR = None

@st.cache_resource
def get_supabase():
    if create_client is None:
        raise ImportError(
            "No se pudo importar el cliente de Supabase. "
            "Instala el paquete con `pip install supabase` o asegúrate de que `requirements.txt` contenga `supabase`."
        ) from _SUPABASE_IMPORT_ERROR

    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_KEY en Streamlit secrets.")

    return create_client(url, key)
