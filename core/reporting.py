from io import BytesIO
from datetime import datetime
import pandas as pd
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from config import ZONA
from services.data import obtener_empleados, obtener_sucursales_catalogo, enriquecer_con_nombre_sucursal


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


def enviar_reporte_diario(df_hoy, zona_usuario=None):
    if df_hoy.empty:
        st.warning("No hay registros hoy")
        return False, None

    df_hoy = enriquecer_con_nombre_sucursal(df_hoy)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_hoy.to_excel(writer, index=False, sheet_name="Resumen")
        if "sucursal_id" in df_hoy.columns:
            for suc_id, grp in df_hoy.groupby("sucursal_id", dropna=False):
                suc_nombre = str(grp["sucursal_nombre"].iloc[0]) if "sucursal_nombre" in grp.columns and pd.notna(grp["sucursal_nombre"].iloc[0]) else f"Suc_{suc_id}"
                hoja = suc_nombre[:31]
                grp.to_excel(writer, index=False, sheet_name=hoja)
    output.seek(0)

    hoy_str = datetime.now(zona_usuario or ZONA).strftime("%Y-%m-%d")

    mensaje = MIMEMultipart()
    smtp_user = st.secrets.get("SMTP_USER")
    smtp_pass = st.secrets.get("SMTP_PASSWORD")
    email_to = st.secrets.get("REPORTE_DIARIO_TO")
    email_cc_raw = st.secrets.get("REPORTE_DIARIO_CC", "")
    cc_list = [x.strip() for x in str(email_cc_raw).split(",") if x.strip()]

    if not smtp_user or not smtp_pass or not email_to:
        st.error("Faltan credenciales de correo en secrets: SMTP_USER, SMTP_PASSWORD, REPORTE_DIARIO_TO")
        return False, None

    mensaje["Subject"] = f"📊 Reporte Diario de Asistencia - {hoy_str}"
    mensaje["From"] = smtp_user
    mensaje["To"] = email_to
    if cc_list:
        mensaje["Cc"] = ", ".join(cc_list)

    retardos = len(df_hoy[df_hoy["estatus"].str.contains("Retardo|CRÍTICO", case=False, na=False)])
    faltas = 0
    try:
        empleados = obtener_empleados()
        presentes = set(df_hoy["empleado"].dropna().unique())
        faltas = len([e for e in empleados if e.get("nombre") not in presentes])
    except Exception:
        faltas = 0

    total_registros = df_hoy["empleado"].nunique()
    detalle_sucursal = ""
    if "sucursal_id" in df_hoy.columns:
        if "sucursal_nombre" in df_hoy.columns:
            corte = df_hoy.groupby("sucursal_nombre").size().reset_index(name="registros")
            detalle_sucursal = "\n".join([f"• {row['sucursal_nombre']}: {row['registros']} registros" for _, row in corte.iterrows()])
        else:
            corte = df_hoy.groupby("sucursal_id").size().reset_index(name="registros")
            detalle_sucursal = "\n".join([f"• Sucursal {row['sucursal_id']}: {row['registros']} registros" for _, row in corte.iterrows()])

    mensaje.attach(MIMEText(
        "Buena tarde,\n\n"
        "Se adjunta el reporte diario de asistencia."
        f" Resumen del día:\n\n"
        f"📝 Total registros: {total_registros}\n"
        f"⏰ Retardos: {retardos}\n"
        f"🚫 Faltantes: {faltas}\n"
        f"\n"
        f"📍 Detalle por sucursal:\n{detalle_sucursal if detalle_sucursal else 'Sin dato de sucursal'}\n"
        f"\n"
        f"Sistema NEOMOTIC ACCESS PRO"
    ))

    part = MIMEBase("application", "octet-stream")
    part.set_payload(output.getvalue())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f"attachment; filename=\"reporte_{hoy_str}.xlsx\"")
    mensaje.attach(part)

    try:
        import smtplib
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(mensaje)
        server.quit()

        hora_envio = datetime.now(zona_usuario or ZONA)
        st.success(f"📧 Reporte diario enviado correctamente ({hora_envio.strftime('%Y-%m-%d %H:%M:%S')})")
        return True, hora_envio
    except Exception as e:
        st.error(f"Error correo: {e}")
        return False, None


def normalizar_resultado_envio(resultado):
    if isinstance(resultado, tuple) and len(resultado) == 2:
        return resultado
    if isinstance(resultado, bool):
        return resultado, None
    return False, None
