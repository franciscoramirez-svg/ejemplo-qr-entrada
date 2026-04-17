import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from core.reporting import exportar_excel, enviar_reporte_diario, normalizar_resultado_envio
from services.data import enriquecer_con_nombre_sucursal, obtener_sucursales_catalogo, obtener_empleados, obtener_registros
from config import ZONA
from io import BytesIO
import qrcode
import zipfile


def _style_admin():
    st.markdown(
        """
        <style>
        .admin-panel {
            background: linear-gradient(135deg, #020617 0%, #070f2b 100%);
            border-radius: 24px;
            padding: 24px;
            color: white;
            margin-bottom: 24px;
            box-shadow: 0 20px 80px rgba(0, 0, 0, 0.3);
        }
        .stat-card {
            border-radius: 22px;
            border: 1px solid rgba(148, 163, 184, 0.2);
            padding: 20px;
            background: rgba(15, 23, 42, 0.75);
        }
        .badge-of-month {
            background: #0f172a;
            padding: 18px;
            border-radius: 20px;
            margin-bottom: 20px;
            border: 1px solid rgba(148, 163, 184, 0.24);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _calculate_employee_of_month(df):
    if df.empty:
        return None
    window = datetime.now(ZONA) - timedelta(days=30)
    df = df[df["fecha_hora"] >= window]
    if df.empty:
        return None

    df_summary = df.copy()
    df_summary["presencia"] = (df_summary["tipo"] == "Entrada").astype(int)
    df_summary["retardo_abs"] = df_summary["min_retardo"].fillna(0).astype(int)
    agg = df_summary.groupby("empleado").agg(
        presencias=("presencia", "sum"),
        retardo=("retardo_abs", "sum"),
    ).reset_index()
    agg["score"] = agg["presencias"] * 10 - agg["retardo"]
    agg = agg.sort_values(["score", "retardo"], ascending=[False, True])
    best = agg.iloc[0]
    return best.to_dict()


def render_admin_dashboard(zona_usuario):
    _style_admin()
    st.markdown("## 📊 Panel ejecutivo")
    st.markdown("<p>Visión clara de asistencias, retardos, faltas y desempeño del equipo.</p>", unsafe_allow_html=True)

    df = enriquecer_con_nombre_sucursal(obtener_registros())
    empleados = obtener_empleados()
    if df.empty:
        st.warning("No hay registros para mostrar en el dashboard.")
        return

    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"], errors="coerce")
    df = df.dropna(subset=["fecha_hora"])
    hoy = df[df["fecha_hora"].dt.date == datetime.now(zona_usuario).date()]
    empleados_hoy = hoy[hoy["tipo"] == "Entrada"]["empleado"].nunique()
    total_empleados = len(empleados)
    retardos = len(hoy[hoy["estatus"].str.contains("Retardo|CRÍTICO", case=False, na=False)])
    salidas_anticipadas = len(hoy[hoy["estatus"] == "SALIDA ANTICIPADA"])
    presentes = len(hoy["empleado"].unique())
    faltantes = [
        e.get("nombre")
        for e in (empleados or [])
        if e.get("nombre") and e.get("nombre") not in set(hoy[hoy["tipo"] == "Entrada"]["empleado"].unique())
    ]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Personas hoy", presentes)
    c2.metric("Retardos", retardos)
    c3.metric("Salidas anticipadas", salidas_anticipadas)
    c4.metric("Faltantes hoy", len(faltantes))

    c5, c6, c7 = st.columns(3)
    c5.metric("Total empleados", total_empleados)
    c6.metric("Asistencia", f"{(presentes / total_empleados * 100) if total_empleados else 0:.1f}%")
    c7.metric("Cobertura", f"{(empleados_hoy / total_empleados * 100) if total_empleados else 0:.1f}%")

    empleado_mes = _calculate_employee_of_month(df)
    if empleado_mes:
        st.markdown(
            f"""
            <div class='badge-of-month'>
                <h3>Empleado del mes</h3>
                <p><strong>{empleado_mes['empleado']}</strong></p>
                <p>Presencias: {empleado_mes['presencias']} · Retardo total: {empleado_mes['retardo']} min</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.subheader("📈 Tendencias")
    col1, col2 = st.columns(2)
    fig1 = px.bar(
        df.groupby(df["fecha_hora"].dt.date).size().reset_index(name="registros"),
        x="fecha_hora",
        y="registros",
        title="Registros diarios"
    )
    col1.plotly_chart(fig1, use_container_width=True)

    fig2 = px.bar(
        df.groupby("empleado")["min_retardo"].sum().reset_index().sort_values("min_retardo", ascending=False),
        x="empleado",
        y="min_retardo",
        title="Minutos de retardo por empleado"
    )
    col2.plotly_chart(fig2, use_container_width=True)

    st.subheader("🗺️ Ubicaciones de registro")
    pts = hoy.dropna(subset=["lat", "lon"])
    if not pts.empty:
        st.map(pts[["lat", "lon"]])
    else:
        st.info("No hay coordenadas registradas para hoy.")

    st.subheader("🚨 Faltantes y avisos")
    if faltantes:
        for nombre in faltantes[:10]:
            st.error(nombre)
    else:
        st.success("Todos los empleados registrados hoy están presentes.")

    st.subheader("🧾 Controles administrativos")
    if st.button("📧 Enviar reporte diario"):
        ok_mail, hora_mail = normalizar_resultado_envio(enviar_reporte_diario(hoy, zona_usuario=zona_usuario))
        st.success("Reporte enviado" if ok_mail else "Error al enviar reporte")
        if hora_mail:
            st.write(hora_mail.strftime("%Y-%m-%d %H:%M:%S"))

    min_fecha = df["fecha_hora"].dt.date.min()
    max_fecha = df["fecha_hora"].dt.date.max()
    col_f1, col_f2 = st.columns(2)
    fecha_inicio = col_f1.date_input("Fecha inicio", value=max_fecha, min_value=min_fecha, max_value=max_fecha)
    fecha_fin = col_f2.date_input("Fecha fin", value=max_fecha, min_value=min_fecha, max_value=max_fecha)

    if fecha_inicio > fecha_fin:
        st.warning("La fecha inicio no puede ser mayor que la fecha fin.")
        fecha_inicio, fecha_fin = fecha_fin, fecha_inicio

    sucursales_cat = obtener_sucursales_catalogo()
    opciones_sucursal = ["Todas"] + (sucursales_cat["nombre"].dropna().tolist() if not sucursales_cat.empty else [])
    sucursal_sel = st.selectbox("Sucursal a exportar", opciones_sucursal)

    mask_rango = (df["fecha_hora"].dt.date >= fecha_inicio) & (df["fecha_hora"].dt.date <= fecha_fin)
    df_export = df[mask_rango].copy()
    df_export = enriquecer_con_nombre_sucursal(df_export)
    if sucursal_sel != "Todas" and "sucursal_nombre" in df_export.columns:
        df_export = df_export[df_export["sucursal_nombre"] == sucursal_sel]

    st.caption(f"Registros para exportar: {len(df_export)}")
    exportar_excel(df_export, file_name=f"reporte_asistencia_{fecha_inicio}_a_{fecha_fin}.xlsx")

    st.subheader("📦 Generar QR de empleados")
    if st.button("Descargar todos los QR (ZIP)"):
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as z:
            for emp in obtener_empleados():
                qr = qrcode.make(emp["nombre"])
                img_bytes = BytesIO()
                qr.save(img_bytes, format="PNG")
                z.writestr(f"{emp['nombre']}.png", img_bytes.getvalue())
        st.download_button("⬇️ Descargar ZIP", zip_buffer.getvalue(), file_name="QR_Empleados.zip", mime="application/zip")

    emp_sel = st.selectbox("Selecciona empleado", [e.get("nombre") for e in obtener_empleados() if e.get("nombre")])
    if emp_sel:
        qr = qrcode.make(emp_sel)
        img_bytes = BytesIO()
        qr.save(img_bytes, format="PNG")
        img_bytes.seek(0)
        st.image(img_bytes, caption=f"QR de {emp_sel}")
        st.download_button("⬇️ Descargar QR individual", img_bytes.getvalue(), file_name=f"{emp_sel}.png", mime="image/png")
