import requests
from datetime import datetime, timedelta
from config import settings
from routers.config_loader import load_config


# =====================================================
# LOAD CONFIGURATION
# =====================================================

CONFIG = load_config()
MACHINES = {m["machine_id"]: m for m in CONFIG["machines"]}


# =====================================================
# INFLUX CONNECTION
# =====================================================

session = requests.Session()


def validate_influx():
    try:
        response = session.get(
            f"{settings.INFLUX_BASE_URL}/ping",
            timeout=5
        )
        return response.status_code == 204
    except Exception:
        return False


def query_influx(query: str):
    response = session.get(
        f"{settings.INFLUX_BASE_URL}/query",
        params={
            "db": settings.INFLUX_DB,
            "q": query,
            "u": settings.INFLUX_USER,
            "p": settings.INFLUX_PASSWORD,
        },
        timeout=10,
    )
    return response.json()


# =====================================================
# INTERNAL HELPERS
# =====================================================

def _safe_value(data):
    try:
        return data["results"][0]["series"][0]["values"][0][1] or 0
    except Exception:
        return 0


def _extend_start_time(start_iso: str, minutes=1):
    """
    Extend start time slightly backward to capture correct FIRST value.
    """
    try:
        dt = datetime.strptime(start_iso, "%Y-%m-%dT%H:%M:%SZ")
        dt -= timedelta(minutes=minutes)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return start_iso


# =====================================================
# PULSE DELTA (CORRECT FOR COUNTERS)
# =====================================================

def _delta_query(measurement, field, start=None, end=None):

    if start and end:
        time_filter = f"time >= '{start}' AND time <= '{end}'"
    else:
        time_filter = "time > now() - 24h"

    query = f"""
    SELECT SUM(nnd) FROM (
        SELECT NON_NEGATIVE_DIFFERENCE("{field}") AS nnd
        FROM "{measurement}"
        WHERE {time_filter}
    )
    """

    return _safe_value(query_influx(query))


# =====================================================
# ENERGY (CUMULATIVE METER — FIXED)
# =====================================================

def _energy_query(measurement, field, start=None, end=None):

    if start and end:
        start = _extend_start_time(start, minutes=1)
        time_filter = f"time >= '{start}' AND time <= '{end}'"
    else:
        time_filter = "time > now() - 24h"

    query = f"""
    SELECT LAST("{field}") - FIRST("{field}") AS energy
    FROM "{measurement}"
    WHERE {time_filter}
    """

    energy = _safe_value(query_influx(query))

    # Protect against meter reset / bad data
    if energy < 0:
        return 0

    return energy


# =====================================================
# RUN HOURS (NEAR REAL-TIME)
# =====================================================

def _run_hours_query(measurement, field, start=None, end=None, interval_minutes=1):

    if start and end:
        time_filter = f"time >= '{start}' AND time <= '{end}'"
    else:
        time_filter = "time > now() - 24h"

    query = f"""
    SELECT NON_NEGATIVE_DIFFERENCE(LAST("{field}"))
    FROM "{measurement}"
    WHERE {time_filter}
    GROUP BY time({interval_minutes}m)
    """

    data = query_influx(query)

    try:
        values = data["results"][0]["series"][0]["values"]
    except Exception:
        return 0

    active_intervals = sum(
        1 for row in values
        if row[1] is not None and row[1] > 0
    )

    run_hours = (active_intervals * interval_minutes) / 60
    return round(run_hours, 2)


# =====================================================
# PUBLIC FUNCTIONS
# =====================================================

def get_pulse_delta_last_24h(machine_id: int):
    m = MACHINES[machine_id]
    return _delta_query(m["measurement"], m["pulse_fields"][0])


def get_energy_delta_last_24h(machine_id: int):
    m = MACHINES[machine_id]

    if not m.get("energy_fields"):
        return 0

    return _energy_query(m["measurement"], m["energy_fields"][0])


def get_run_hours_last_24h(machine_id: int):
    m = MACHINES[machine_id]
    return _run_hours_query(m["measurement"], m["pulse_fields"][0])


def get_pulse_delta_between(machine_id, start, end):
    m = MACHINES[machine_id]
    return _delta_query(
        m["measurement"],
        m["pulse_fields"][0],
        start,
        end
    )


def get_energy_delta_between(machine_id, start, end):
    m = MACHINES[machine_id]

    if not m.get("energy_fields"):
        return 0

    return _energy_query(
        m["measurement"],
        m["energy_fields"][0],
        start,
        end
    )


def get_run_hours_between(machine_id, start, end, interval_minutes=1):
    m = MACHINES[machine_id]
    return _run_hours_query(
        m["measurement"],
        m["pulse_fields"][0],
        start,
        end,
        interval_minutes
    )


# =====================================================
# REAL-TIME DEBUG (OPTIONAL)
# =====================================================

def get_latest_energy_reading(machine_id: int):
    m = MACHINES[machine_id]

    if not m.get("energy_fields"):
        return 0

    query = f"""
    SELECT LAST("{m["energy_fields"][0]}")
    FROM "{m["measurement"]}"
    """

    return _safe_value(query_influx(query))