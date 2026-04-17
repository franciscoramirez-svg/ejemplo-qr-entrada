from __future__ import annotations

from datetime import datetime


def format_datetime() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M")
