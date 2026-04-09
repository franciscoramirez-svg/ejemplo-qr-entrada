import os
import smtplib
from io import BytesIO
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

import pandas as pd
import pytz
from supabase import create_client


def get_env(name: str, required: bool = True, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing env var: {name}")
    return value


def main() -> None:
    supabase_url = get_env("SUPABASE_URL")
    supabase_key = get_env("SUPABASE_KEY")
    smtp_user = get_env("SMTP_USER")
    smtp_password = get_env("SMTP_PASSWORD")
    reporte_to = get_env("REPORTE_DIARIO_TO")
    reporte_cc = os.getenv("REPORTE_DIARIO_CC", "")
    timezone_name = os.getenv("REPORTE_TIMEZONE", "America/Mexico_City")

    zona = pytz.timezone(timezone_name)
    ahora = datetime.now(zona)
    hoy = ahora.date()
    hoy_str = ahora.strftime("%Y-%m-%d")

    supabase = create_client(supabase_url, supabase_key)

    registros = pd.DataFrame(supabase.table("registros").select("*").execute().data or [])
    if registros.empty:
        print("No hay registros en la base de datos.")
        return

    registros["fecha_hora"] = pd.to_datetime(registros["fecha_hora"], errors="coerce")
    registros = registros.dropna(subset=["fecha_hora"])
    df_hoy = registros[registros["fecha_hora"].dt.date == hoy].copy()

    if df_hoy.empty:
        print(f"No hay registros para hoy ({hoy_str}).")
        return

    sucursales = pd.DataFrame(supabase.table("sucursales").select("id,nombre").execute().data or [])
    if not sucursales.empty and "sucursal_id" in df_hoy.columns:
        sucursales["id"] = sucursales["id"].astype(str)
        df_hoy["sucursal_id"] = df_hoy["sucursal_id"].astype(str)
        df_hoy = df_hoy.merge(
            sucursales.rename(columns={"id": "sucursal_id", "nombre": "sucursal_nombre"}),
            on="sucursal_id",
            how="left",
        )

    empleados = supabase.table("empleados").select("nombre").execute().data or []
    presentes = set(df_hoy["empleado"].dropna().unique()) if "empleado" in df_hoy.columns else set()
    faltas = len([e for e in empleados if e.get("nombre") not in presentes])
    retardos = len(df_hoy[df_hoy["estatus"].astype(str).str.contains("Retardo|CRÍTICO", case=False, na=False)])

    detalle_sucursal = ""
    if "sucursal_nombre" in df_hoy.columns:
        corte = df_hoy.groupby("sucursal_nombre").size().reset_index(name="registros")
        detalle_sucursal = "\n".join([f"• {r['sucursal_nombre']}: {r['registros']} registros" for _, r in corte.iterrows()])

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_hoy.to_excel(writer, index=False, sheet_name="Resumen")
        if "sucursal_nombre" in df_hoy.columns:
            for suc_nombre, grp in df_hoy.groupby("sucursal_nombre", dropna=False):
                hoja = str(suc_nombre)[:31] if pd.notna(suc_nombre) else "SinSucursal"
                grp.to_excel(writer, index=False, sheet_name=hoja)
    output.seek(0)

    mensaje = MIMEMultipart()
    mensaje["Subject"] = f"📊 Reporte Diario de Asistencia - {hoy_str}"
    mensaje["From"] = smtp_user
    mensaje["To"] = reporte_to

    cc_list = [x.strip() for x in reporte_cc.split(",") if x.strip()]
    if cc_list:
        mensaje["Cc"] = ", ".join(cc_list)

    mensaje.attach(
        MIMEText(
            "Buena tarde,\n\n"
            "Se adjunta el reporte diario de asistencia.\n\n"
            f"📝 Total registros: {len(df_hoy)}\n"
            f"⏰ Retardos: {retardos}\n"
            f"🚫 Faltantes: {faltas}\n\n"
            f"📍 Detalle por sucursal:\n{detalle_sucursal if detalle_sucursal else 'Sin dato de sucursal'}\n\n"
            "Sistema NEOMOTIC ACCESS PRO"
        )
    )

    part = MIMEBase("application", "octet-stream")
    part.set_payload(output.getvalue())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="reporte_{hoy_str}.xlsx"')
    mensaje.attach(part)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(mensaje)

    print(f"Reporte enviado correctamente: {hoy_str} {ahora.strftime('%H:%M:%S')} ({timezone_name})")


if __name__ == "__main__":
    main()
