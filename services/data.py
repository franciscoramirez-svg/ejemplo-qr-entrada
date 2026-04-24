import pandas as pd
from services.supabase_client import get_supabase

supabase = get_supabase()


def obtener_registros():
    data = supabase.table("registros").select("*").execute().data
    return pd.DataFrame(data if data else [])


def obtener_empleados():
    return supabase.table("empleados").select("*").execute().data or []


def obtener_sucursales_catalogo():
    try:
        data = supabase.table("sucursales").select("id,nombre,lat,lon").execute().data or []
    except Exception:
        data = supabase.table("sucursales").select("id,nombre").execute().data or []
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df["id"] = df["id"].astype(str)
    return df


def obtener_sucursal_por_id(sucursal_id):
    res = supabase.table("sucursales").select("*").eq("id", sucursal_id).execute()
    return res.data[0] if res.data else None


def obtener_timezone_sucursal(sucursal_id):
    suc = obtener_sucursal_por_id(sucursal_id)
    if suc and suc.get("timezone"):
        return str(suc["timezone"])
    return None


def enriquecer_con_nombre_sucursal(df):
    if df.empty or "sucursal_id" not in df.columns:
        return df
    cat = obtener_sucursales_catalogo()
    if cat.empty:
        return df
    out = df.copy()
    out["sucursal_id"] = out["sucursal_id"].astype(str)
    return out.merge(
        cat.rename(columns={"id": "sucursal_id", "nombre": "sucursal_nombre"}),
        on="sucursal_id",
        how="left"
    )


def actualizar_registro_justificacion(registro_id, motivo):
    return supabase.table("registros").update({"justificacion": motivo}).eq("id", registro_id).execute()


def registro_existe(registro_id):
    resultado = supabase.table("registros").select("id").eq("id", registro_id).execute()
    return bool(resultado.data)
