"""
Structured ID generation.
Format: {PREFIX}-{YYYYMMDD}-{HHMMSS}
Example: BRD-F-20260921-075204
"""
from datetime import datetime
from modules.constants import ID_PREFIXES


def generate_id(prefix_key: str) -> str:
    """
    Generate a structured ID like 'BRD-F-20260921-075204'.

    Args:
        prefix_key: key in ID_PREFIXES (e.g., 'breeder_female', 'tank')

    Returns:
        Structured ID string
    """
    prefix = ID_PREFIXES.get(prefix_key, prefix_key.upper())
    now = datetime.now()
    return f"{prefix}-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}"


def parse_id(structured_id: str) -> dict:
    """
    Parse 'BRD-F-20260921-075204' into components.

    Returns:
        {"prefix": "BRD-F", "date": "2026-09-21", "time": "07:52:04"}
        or None if the format doesn't match.
    """
    try:
        parts = structured_id.rsplit("-", 2)
        prefix = parts[0]
        date_str = parts[1]
        time_str = parts[2]
        parsed = datetime.strptime(date_str + time_str, "%Y%m%d%H%M%S")
        return {
            "prefix": prefix,
            "date":   parsed.strftime("%Y-%m-%d"),
            "time":   parsed.strftime("%H:%M:%S"),
        }
    except (ValueError, IndexError):
        return None
