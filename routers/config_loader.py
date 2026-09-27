import os


def load_config(path=None):

    if path is None:
        path = os.path.join(os.path.dirname(__file__), "config.txt")

    machines = []
    measurements = []
    current = {}

    with open(path) as f:

        for line in f:

            line = line.strip()

            if not line:
                continue

            if line.startswith("MEASUREMENTS"):
                continue

            if line.startswith("machines"):
                continue

            # Raw measurement IDs
            if ":" not in line:
                measurements.append(line)
                continue

            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            # New machine block
            if key == "machine_key" and current:
                machines.append(current)
                current = {}

            # ===============================
            # TYPE CASTING (UPDATED)
            # ===============================

            if key in ["machine_id", "pulses_per_revolution"]:
                value = int(value)

            elif key in ["meters_per_revolution"]:
                value = float(value)

            elif key in ["pulse_fields", "energy_fields"]:
                value = [v.strip() for v in value.split(",") if v.strip()]

            current[key] = value

        if current:
            machines.append(current)

    return {
        "measurements": measurements,
        "machines": machines
    }