from database import SessionLocal
from models import MachineConfig, HourlyProduction, ShiftProduction
from utils.aggregations import calculate_shift_data
from utils.influx import (
    get_pulse_delta_between,
    get_energy_delta_between,
    get_run_hours_between,
)

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")


# ===============================
# HOURLY AGGREGATION
# ===============================
def run_hourly_aggregation():
    db = SessionLocal()

    now_ist = datetime.now(IST)
    hour_end = now_ist.replace(minute=0, second=0, microsecond=0)
    hour_start = hour_end - timedelta(hours=1)

    start_iso = hour_start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = hour_end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    machines = db.query(MachineConfig).all()

    for m in machines:

        pulse_delta = get_pulse_delta_between(m.machine_id, start_iso, end_iso)
        energy_delta = get_energy_delta_between(m.machine_id, start_iso, end_iso)
        run_hours = get_run_hours_between(m.machine_id, start_iso, end_iso)

        production = (pulse_delta / m.pulses_per_revolution) * m.meters_per_revolution if m.pulses_per_revolution else 0

        energy_per_meter = energy_delta / production if production > 0 else 0

        existing = db.query(HourlyProduction).filter(
            HourlyProduction.machine_id == m.machine_id,
            HourlyProduction.timestamp == hour_start
        ).first()

        if not existing:
            db.add(HourlyProduction(
                machine_id=m.machine_id,
                timestamp=hour_start,
                run_hours=round(run_hours, 3),
                production_meters=round(production, 3),
                energy_kwh=round(energy_delta, 3),
                energy_per_meter=round(energy_per_meter, 5),
            ))

    db.commit()
    db.close()


# ===============================
# SHIFT AGGREGATION
# ===============================
def run_shift_aggregation():
    db = SessionLocal()

    machines = db.query(MachineConfig).all()

    for m in machines:
        shift_data = calculate_shift_data(m)

        today = datetime.now(IST).date()

        for s in shift_data["shifts"]:

            existing = db.query(ShiftProduction).filter(
                ShiftProduction.machine_id == m.machine_id,
                ShiftProduction.date == today,
                ShiftProduction.shift == s["shift"]
            ).first()

            if existing:
                # update live (important for near real-time history)
                existing.run_hours = s["run_hours"]
                existing.production_meters = s["production_meters"]
                existing.energy_kwh = s["energy_kwh"]
                existing.energy_per_meter = s["energy_per_meter"]
                existing.machine_speed_mpm = s["machine_speed_mpm"]

            else:
                db.add(ShiftProduction(
                    machine_id=m.machine_id,
                    date=today,
                    shift=s["shift"],
                    run_hours=s["run_hours"],
                    production_meters=s["production_meters"],
                    energy_kwh=s["energy_kwh"],
                    energy_per_meter=s["energy_per_meter"],
                    machine_speed_mpm=s["machine_speed_mpm"],
                ))

    db.commit()
    db.close()