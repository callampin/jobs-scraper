"""Conversión y validación de fechas con zona horaria explícita."""

from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def as_utc(value: datetime) -> datetime:
    """Convierte un datetime consciente de zona horaria a UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("La fecha debe incluir zona horaria")
    return value.astimezone(UTC)


def isoformat_z(value: datetime) -> str:
    """Devuelve una fecha ISO 8601 en UTC, con segundos y sufijo Z."""
    return as_utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def from_unix_timestamp(value: object) -> datetime | None:
    """Convierte segundos Unix a UTC; devuelve None para valores inválidos."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def parse_iso_datetime(value: str) -> datetime:
    """Lee una fecha ISO 8601 y verifica que tenga zona horaria."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return as_utc(parsed)


def cutoff_date(now: datetime, days: int) -> datetime:
    """Calcula el límite inferior inclusivo para una ventana de días."""
    if days < 1:
        raise ValueError("days debe ser mayor o igual que 1")
    return as_utc(now) - timedelta(days=days)
