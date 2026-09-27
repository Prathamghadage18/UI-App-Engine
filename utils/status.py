from utils.influx import query_influx
from routers.config_loader import load_config


# Minimum pulse delta required to consider machine running
RUN_THRESHOLD = 1

# Load machine configuration
CONFIG = load_config()
MACHINES = {m["machine_id"]: m for m in CONFIG["machines"]}


def get_machine_status(machine_id: int) -> str:
    """
    Determine machine RUN/STOP status based on pulse activity
    in the last 5 minutes.

    Logic:
    - Query pulse counter
    - Calculate non-negative pulse difference
    - If pulses detected → RUN
    - If no pulses → STOP
    """

    try:
        machine = MACHINES[machine_id]
        pulse_field = machine["pulse_fields"][0]  # Use first pulse field
        measurement = machine["measurement"]
    except (KeyError, IndexError):
        return "STOP"

    query = f"""
    SELECT SUM(nnd) FROM (
        SELECT NON_NEGATIVE_DIFFERENCE("{pulse_field}") AS nnd
        FROM "{measurement}"
        WHERE id='{machine_id}'
        AND time > now() - 5m
    )
    """

    try:
        data = query_influx(query)

        results = data.get("results", [])
        if not results:
            return "STOP"

        series = results[0].get("series")
        if not series:
            return "STOP"

        values = series[0].get("values")
        if not values:
            return "STOP"

        delta = values[0][1] or 0

        if delta >= RUN_THRESHOLD:
            return "RUN"

        return "STOP"

    except Exception:
        return "STOP"