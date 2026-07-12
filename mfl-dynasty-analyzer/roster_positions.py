from __future__ import annotations


def position_group(position: str) -> str:
    if position in {"DT", "DE"}:
        return "DT+DE"
    if position in {"CB", "S"}:
        return "CB+S"
    return position
