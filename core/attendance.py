import hashlib
import hmac
from datetime import datetime, date, time, timedelta
from math import radians, cos, sin, asin, sqrt

import pandas as pd
from config import ZONA
from services.data import obtener_registros, obtener_sucursal_por_id
from services.data import supabase


def migrar_pines():
    res = supabase.table("empleados").select("*").execute()
    if not res.data:
        print("❌ No hay empleados")
        return

    total = len(res.data)
    migrados = 0

    for emp in res.data:
        emp_id = emp["id"]
        pin = emp.get("pin")
        pin_hash = emp.get("pin_hash")

        if pin_hash:
            continue

        if not pin:
            print(f"⚠️ Empleado sin PIN: {emp['nombre']}")
            continue

        hash_generado = hashlib.sha256(str(pin).encode()).hexdigest()
        supabase.table("empleados").update({"pin_hash": hash_generado}).eq("id", emp_id).execute()
        print(f"✅ Migrado: {emp['nombre']}")
        migrados += 1

    print("\n🎯 RESULTADO:")
    print(f"Total empleados: {total}")
    print(f"Migrados: {migrados}")
    print(f"Ya tenían hash: {total - migrados}")


def distancia_metros(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def validar_geocerca(lat, lon, sucursal_id):
    if not sucursal_id:
        return False, "❌ No tienes sucursal asignada"

    suc = obtener_sucursal_por_id(sucursal_id)
    if not suc:
        return False, "❌ Sucursal no registrada en sistema"

    dist = distancia_metros(lat, lon, suc["lat"], suc["lon"])
    if dist > suc.get("radio", 100):
        return False, "❌ Estás fuera de la sucursal"

    return True, ""


def existe_registro_duplicado(nombre, tipo, ahora, ventana_min=2):
    df = obtener_registros()
    if df.empty:
        return False

    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"], errors="coerce")
    df = df.dropna(subset=["fecha_hora"])
    if df.empty:
        return False

    hoy = ahora.date()
    cand = df[(df["empleado"] == nombre) & (df["tipo"] == tipo) & (df["fecha_hora"].dt.date == hoy)]
    if cand.empty:
        return False

    ultimo = cand.sort_values("fecha_hora").iloc[-1]["fecha_hora"]
    if hasattr(ultimo, "tzinfo") and ultimo.tzinfo is not None:
        ultimo = ultimo.tz_convert(ZONA).to_pydatetime().replace(tzinfo=None)
    else:
        ultimo = pd.Timestamp(ultimo).to_pydatetime()

    delta_min = abs((ahora.replace(tzinfo=None) - ultimo).total_seconds() / 60)
    return delta_min <= ventana_min


def validar_pin(empleado, pin_input):
    pin_hash = empleado.get("pin_hash")
    if pin_hash:
        pin_input_hash = hashlib.sha256(pin_input.encode("utf-8")).hexdigest()
        return hmac.compare_digest(pin_input_hash, str(pin_hash))

    pin_legacy = empleado.get("pin")
    if pin_legacy is None:
        return False
    return hmac.compare_digest(str(pin_legacy), pin_input)


def validar_flujo(nombre, tipo):
    df = obtener_registros()
    if df.empty:
        return True, ""

    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"], errors="coerce")
    df = df.dropna(subset=["fecha_hora"])
    if df.empty:
        return True, ""

    emp = df[df["empleado"] == nombre]
    if emp.empty:
        if tipo == "Salida":
            return False, "⚠️ No puedes salir sin entrar"
        return True, ""

    ultimo_tipo = emp.sort_values("fecha_hora").iloc[-1]["tipo"]
    if tipo == "Entrada":
        if ultimo_tipo == "Entrada":
            return False, "⚠️ Debes justificar salida faltante"
        return True, ""

    if tipo == "Salida":
        if ultimo_tipo == "Salida":
            return False, "⚠️ Ya registraste salida"
        if ultimo_tipo != "Entrada":
            return False, "⚠️ No puedes salir sin entrar"
        return True, ""

    return True, ""


def calcular_estatus(tipo, ahora, hora_entrada, hora_salida):
    est = "A Tiempo"
    min_r = 0
    if tipo == "Entrada":
        diff = (datetime.combine(ahora.date(), ahora.time()) - datetime.combine(ahora.date(), hora_entrada)).total_seconds() / 60
        min_r = max(0, int(diff))
        if min_r > 30:
            est = "RETARDO CRÍTICO"
        elif min_r > 15:
            est = "Retardo"
    elif tipo == "Salida":
        if ahora.time() < hora_salida:
            est = "SALIDA ANTICIPADA"
    return est, min_r


def get_week_start(fecha):
    return fecha - timedelta(days=fecha.weekday())


def contar_faltas_semana(nombre, fecha_referencia=None):
    if fecha_referencia is None:
        fecha_referencia = datetime.now(ZONA).date()

    df = obtener_registros()
    if df.empty:
        return 0

    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"], errors="coerce")
    df = df.dropna(subset=["fecha_hora"])
    if df.empty:
        return 0

    df["fecha"] = df["fecha_hora"].dt.date
    semana_inicio = get_week_start(fecha_referencia)
    semana_df = df[(df["fecha"] >= semana_inicio) & (df["fecha"] <= fecha_referencia)]
    faltas = 0

    for dia in semana_df["fecha"].unique():
        diario = semana_df[semana_df["fecha"] == dia]
        if (diario["tipo"] == "Entrada").any() and not (diario["tipo"] == "Salida").any():
            faltas += 1

    return faltas


def cerrar_entradas_abiertas_anteriores(nombre, zona):
    df = obtener_registros()
    if df.empty:
        return []

    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"], errors="coerce")
    df = df.dropna(subset=["fecha_hora"])
    if df.empty:
        return []

    df["fecha"] = df["fecha_hora"].dt.date
    today = datetime.now(zona).date()
    cerrados = []

    for registro_fecha in sorted(df[df["fecha"] < today]["fecha"].unique()):
        diario = df[df["fecha"] == registro_fecha]
        if (diario["tipo"] == "Entrada").any() and not (diario["tipo"] == "Salida").any():
            if diario["justificacion"].astype(str).str.contains("NO DIO SALIDA", case=False, na=False).any():
                continue

            sucursal_id = diario.iloc[0].get("sucursal_id")
            fecha_cierre = datetime.combine(registro_fecha, time(23, 59, 59))
            supabase.table("registros").insert({
                "empleado": nombre,
                "fecha_hora": fecha_cierre.isoformat(),
                "lat": diario.iloc[0].get("lat"),
                "lon": diario.iloc[0].get("lon"),
                "tipo": "Salida",
                "estatus": "NO DIO SALIDA",
                "min_retardo": 0,
                "sucursal_id": str(sucursal_id) if sucursal_id is not None else None,
                "justificacion": "NO DIO SALIDA",
                "horas_extra": False,
            }).execute()
            cerrados.append(str(registro_fecha))

    return cerrados
