from __future__ import annotations

import hashlib


def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


def verify_pin(pin: str, hashed_pin: str) -> bool:
    return hash_pin(pin) == hashed_pin
