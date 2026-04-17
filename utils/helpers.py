from __future__ import annotations

import streamlit as st


def inject_global_styles() -> None:
    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;800&family=Space+Grotesk:wght@400;500;700&display=swap');

            :root {
                --bg: #07111f;
                --bg-soft: rgba(10, 22, 40, 0.78);
                --line: rgba(120, 208, 255, 0.18);
                --primary: #5ef2ff;
                --secondary: #80ffb8;
                --text: #eaf7ff;
                --muted: #92abc6;
                --danger: #ff6b88;
            }

            .stApp {
                background:
                    radial-gradient(circle at top left, rgba(94, 242, 255, 0.18), transparent 28%),
                    radial-gradient(circle at top right, rgba(128, 255, 184, 0.14), transparent 24%),
                    linear-gradient(135deg, #02060d 0%, #07111f 55%, #0b1730 100%);
                color: var(--text);
                font-family: 'Space Grotesk', sans-serif;
            }

            h1, h2, h3 {
                font-family: 'Orbitron', sans-serif;
                letter-spacing: 0.04em;
                color: var(--text);
            }

            .hero-card, .glass-panel, .section-header {
                border: 1px solid var(--line);
                background: linear-gradient(180deg, rgba(12, 25, 43, 0.9), rgba(6, 14, 25, 0.72));
                box-shadow: 0 20px 60px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.04);
                backdrop-filter: blur(16px);
                border-radius: 26px;
            }

            .hero-card {
                padding: 44px 32px;
                margin-bottom: 24px;
                text-align: center;
            }

            .logo-orbit {
                width: 112px;
                height: 112px;
                margin: 0 auto 18px;
                border-radius: 50%;
                display: grid;
                place-items: center;
                border: 1px solid rgba(94, 242, 255, 0.45);
                box-shadow: 0 0 40px rgba(94, 242, 255, 0.18);
                background:
                    radial-gradient(circle, rgba(94, 242, 255, 0.20), transparent 62%),
                    conic-gradient(from 90deg, rgba(94, 242, 255, 0.1), rgba(128, 255, 184, 0.32), rgba(94, 242, 255, 0.1));
            }

            .logo-core {
                width: 72px;
                height: 72px;
                border-radius: 22px;
                display: grid;
                place-items: center;
                font-family: 'Orbitron', sans-serif;
                font-size: 2rem;
                font-weight: 800;
                color: #03131c;
                background: linear-gradient(135deg, var(--primary), var(--secondary));
            }

            .hero-company, .eyebrow {
                text-transform: uppercase;
                letter-spacing: 0.2em;
                font-size: 0.8rem;
                color: var(--primary);
            }

            .hero-copy {
                color: var(--muted);
                max-width: 760px;
                margin: 0 auto;
            }

            .hero-badges {
                margin-top: 20px;
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
                justify-content: center;
            }

            .hero-badges span {
                padding: 8px 14px;
                border-radius: 999px;
                background: rgba(94, 242, 255, 0.08);
                border: 1px solid rgba(94, 242, 255, 0.18);
                color: var(--text);
                font-size: 0.88rem;
            }

            .glass-panel {
                padding: 22px;
                min-height: 100%;
            }

            .section-header {
                padding: 22px 26px;
                margin-bottom: 20px;
            }

            div[data-testid="stMetric"] {
                border: 1px solid var(--line);
                background: rgba(8, 19, 34, 0.76);
                padding: 12px;
                border-radius: 20px;
            }

            div[data-testid="stForm"] {
                border: 1px solid var(--line);
                border-radius: 24px;
                background: rgba(5, 14, 25, 0.68);
                padding: 16px;
            }

            .stButton > button, .stDownloadButton > button {
                border-radius: 16px;
                min-height: 48px;
                border: 1px solid rgba(94, 242, 255, 0.32);
                background: linear-gradient(135deg, rgba(94, 242, 255, 0.14), rgba(128, 255, 184, 0.10));
                color: white;
                font-weight: 700;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
