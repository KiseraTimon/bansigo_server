# utilities/time_utils.py

from datetime import datetime, timezone

def utc_now() -> datetime:
    """
    generates timezone-aware time
    :return: datetime
    """
    return datetime.now(timezone.utc)


def get_timestamp_id() -> str:
    """
    generates a timestamp for use in naming files and for references
    :return: str
    """

    return utc_now().strftime("%Y%m%d%H%M%S")
