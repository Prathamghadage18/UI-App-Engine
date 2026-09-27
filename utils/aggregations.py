from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from utils.influx import (
    get_pulse_delta_between,
    get_energy_delta_between,
    get_run_hours_between,
)

from utils.status import get_machine_status
from models import DailyProduction
from database import SessionLocal


# ===============================
# OPERATIONAL DAY (IST 07:00 RESET)
# ===============================

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")
RESET_HOUR_IST = 7


def get_operational_day_start_ist(now_ist=None):
    ref_now = now_ist or datetime.now(IST)
    today_reset = ref_now.replace(
        hour=RESET_HOUR_IST,
        minute=0,
        second=0,
        microsecond=0,
    )

    if ref_now < today_reset:
        return today_reset - timedelta(days=1), ref_now

    return today_reset, ref_now


def get_operational_day_token(now_ist=None):
    op_start, _ = get_operational_day_start_ist(now_ist)
    return op_start.strftime("%Y%m%dT%H%M")


# ===============================
# 🆕 PRODUCTION CALCULATION (CORRECT LOGIC)
# ===============================

def calculate_production(pulse_delta, machine_config):
    """
    Convert pulses → meters using machine physics
    """
    ppr = machine_config.pulses_per_revolution
    m_per_rev = machine_config.meters_per_revolution

    if not ppr or not m_per_rev:
        return 0

    return (pulse_delta / ppr) * m_per_rev


# ===============================
# SNAPSHOT (Operational Day)
# ===============================

def calculate_snapshot(machine_config):

    op_start_ist, now_ist = get_operational_day_start_ist()
    start_iso = op_start_ist.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = now_ist.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    pulse_delta = get_pulse_delta_between(
        machine_config.machine_id, start_iso, end_iso
    )

    energy_delta = get_energy_delta_between(
        machine_config.machine_id, start_iso, end_iso
    )

    run_hours = get_run_hours_between(
        machine_config.machine_id, start_iso, end_iso
    )

    # ✅ FIXED
    production_meters = calculate_production(pulse_delta, machine_config)

    energy_per_meter = (
        energy_delta / production_meters
        if production_meters > 0 else 0
    )

    return {
        "machine_name": machine_config.machine_name,
        "location": machine_config.location,
        "status": get_machine_status(machine_config.machine_id),
        "run_hours": round(run_hours, 2),
        "production_meters": round(production_meters, 2),
        "energy_kwh": round(energy_delta, 2),
        "energy_per_meter": round(energy_per_meter, 4),
    }


# ===============================
# SHIFT ANALYTICS
# ===============================

def calculate_shift_data(machine_config):
    op_start_ist, now_ist = get_operational_day_start_ist()
    op_day = op_start_ist.date()

    shifts = [
        ("Shift 1", machine_config.shift1_start, machine_config.shift1_end),
        ("Shift 2", machine_config.shift2_start, machine_config.shift2_end),
        ("Shift 3", machine_config.shift3_start, machine_config.shift3_end),
    ]

    results = []

    for name, start, end in shifts:

        start_dt_ist = datetime.strptime(
            f"{op_day} {start}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=IST)

        end_dt_ist = datetime.strptime(
            f"{op_day} {end}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=IST)

        if end_dt_ist <= start_dt_ist:
            end_dt_ist += timedelta(days=1)

        if now_ist < start_dt_ist:
            results.append({
                "shift": name,
                "run_hours": 0,
                "production_meters": 0,
                "production_rate_mph": 0,
                "machine_speed_mpm": 0,
                "energy_kwh": 0,
                "energy_per_meter": 0,
            })
            continue

        is_active = start_dt_ist <= now_ist < end_dt_ist
        effective_end = now_ist if is_active else end_dt_ist

        start_iso = start_dt_ist.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_iso = effective_end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        pulse_delta = get_pulse_delta_between(
            machine_config.machine_id, start_iso, end_iso
        )

        energy_delta = get_energy_delta_between(
            machine_config.machine_id, start_iso, end_iso
        )

        rh_interval = 1 if is_active else 5

        run_hours = get_run_hours_between(
            machine_config.machine_id,
            start_iso,
            end_iso,
            interval_minutes=rh_interval,
        )

        # ✅ FIXED PRODUCTION
        production = calculate_production(pulse_delta, machine_config)

        production_rate = (
            production / run_hours if run_hours > 0 else 0
        )

        energy_per_meter = (
            energy_delta / production if production > 0 else 0
        )

        run_minutes = run_hours * 60

        speed_m_per_min = (
            production / run_minutes if run_minutes > 0 else 0
        )

        results.append({
            "shift": name,
            "run_hours": round(run_hours, 2),
            "production_meters": round(production, 2),
            "production_rate_mph": round(production_rate, 2),
            "machine_speed_mpm": round(speed_m_per_min, 2),
            "energy_kwh": round(energy_delta, 2),
            "energy_per_meter": round(energy_per_meter, 4),
        })

    active_shifts = [r for r in results if r["run_hours"] > 0]

    best_rate = max([r["production_rate_mph"] for r in active_shifts], default=0)

    for r in results:
        r["performance_index"] = (
            round(r["production_rate_mph"] / best_rate, 2)
            if best_rate > 0 and r["run_hours"] > 0 else 0
        )

    underperforming_shift = (
        min(active_shifts, key=lambda x: x["production_rate_mph"])["shift"]
        if active_shifts else None
    )

    return {
        "shifts": results,
        "underperforming_shift": underperforming_shift,
        "server_hour_ist": now_ist.hour,
    }


# ===============================
# DAILY AGGREGATION
# ===============================

def calculate_and_store_daily(machine_config, target_date):

    IST = ZoneInfo("Asia/Kolkata")
    UTC = ZoneInfo("UTC")

    start_dt_ist = datetime.combine(
        target_date,
        datetime.min.time()
    ).replace(tzinfo=IST)

    end_dt_ist = start_dt_ist + timedelta(days=1)

    start_iso = start_dt_ist.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end_dt_ist.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    pulse_delta = get_pulse_delta_between(
        machine_config.machine_id, start_iso, end_iso
    )

    energy_delta = get_energy_delta_between(
        machine_config.machine_id, start_iso, end_iso
    )

    run_hours = get_run_hours_between(
        machine_config.machine_id, start_iso, end_iso
    )

    # ✅ FIXED
    production = calculate_production(pulse_delta, machine_config)

    energy_per_meter = (
        energy_delta / production if production > 0 else 0
    )

    db = SessionLocal()

    existing = db.query(DailyProduction).filter(
        DailyProduction.machine_id == machine_config.machine_id,
        DailyProduction.date == target_date
    ).first()

    if not existing:
        db.add(DailyProduction(
            machine_id=machine_config.machine_id,
            date=target_date,
            production_meters=production,
            run_hours=run_hours,
            energy_kwh=energy_delta,
            energy_per_meter=energy_per_meter,
        ))
    else:
        existing.production_meters = production
        existing.run_hours = run_hours
        existing.energy_kwh = energy_delta
        existing.energy_per_meter = energy_per_meter

    db.commit()
    db.close()