from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, date, timedelta
from typing import Optional

from database import get_db
from models import MachineConfig, DailyProduction, HourlyProduction, ShiftProduction
from utils.influx import validate_influx
from utils.aggregations import (
    calculate_snapshot,
    calculate_shift_data,
    calculate_and_store_daily,
    get_operational_day_token,
)
from utils.status import get_machine_status
from utils.cache import get_cache, set_cache
from routers.config_loader import load_config


router = APIRouter(prefix="/api", tags=["API"])


# ======================================
# CACHE CONFIG (ALIGNED WITH UI)
# ======================================

CACHE_TTL_SHIFTS = 2        # near real-time
CACHE_TTL_SNAPSHOT = 15     # stable 24h view
CACHE_TTL_WEEKLY = 1800     # 30 min


# ======================================
# LOAD CONFIG
# ======================================

CONFIG = load_config()
CONFIG_MACHINES = CONFIG["machines"]


# ======================================
# HEALTH
# ======================================

@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/db-test")
def db_test(db: Session = Depends(get_db)):
    result = db.execute(text("SELECT 1"))
    return {"database": "connected", "result": result.scalar()}


@router.get("/influx-test")
def influx_test():
    return {"influx_connected": validate_influx()}


# ======================================
# INIT MACHINES
# ======================================

@router.post("/init-machines")
def init_machines(db: Session = Depends(get_db)):

    created = 0
    updated = 0

    for m in CONFIG_MACHINES:

        machine = db.query(MachineConfig).filter(
            MachineConfig.machine_key == m["machine_key"]
        ).first()

        if not machine:

            db.add(
                MachineConfig(
                    machine_key=m["machine_key"],
                    machine_id=m["machine_id"],
                    machine_name=m["machine_name"],
                    location=m["location"],

                    # ⚠️ NEW FIELDS (must exist in DB model)
                    pulses_per_revolution=m["pulses_per_revolution"],
                    meters_per_revolution=m["meters_per_revolution"],

                    shift1_start=m["shift1_start"],
                    shift1_end=m["shift1_end"],
                    shift2_start=m["shift2_start"],
                    shift2_end=m["shift2_end"],
                    shift3_start=m["shift3_start"],
                    shift3_end=m["shift3_end"],
                )
            )
            created += 1

        else:
            machine.machine_name = m["machine_name"]
            machine.location = m["location"]

            # ✅ UPDATED
            machine.pulses_per_revolution = m["pulses_per_revolution"]
            machine.meters_per_revolution = m["meters_per_revolution"]

            machine.shift1_start = m["shift1_start"]
            machine.shift1_end = m["shift1_end"]
            machine.shift2_start = m["shift2_start"]
            machine.shift2_end = m["shift2_end"]
            machine.shift3_start = m["shift3_start"]
            machine.shift3_end = m["shift3_end"]

            updated += 1

    db.commit()

    return {
        "status": "machines synchronized",
        "created": created,
        "updated": updated
    }


# ======================================
# LIST MACHINES
# ======================================

@router.get("/machines")
def get_machines(db: Session = Depends(get_db)):
    machines = db.query(MachineConfig).all()
    return [
        {
            "machine_key": m.machine_key,
            "machine_id": m.machine_id,
            "machine_name": m.machine_name,
            "location": m.location,
        }
        for m in machines
    ]


# ======================================
# SNAPSHOT (STABLE VIEW)
# ======================================

@router.get("/snapshot/{machine_key}")
def get_snapshot(machine_key: str, db: Session = Depends(get_db)):

    machine = db.query(MachineConfig).filter(
        MachineConfig.machine_key == machine_key
    ).first()

    if not machine:
        return {"error": "Machine not found"}

    day_token = get_operational_day_token()
    cache_key = f"snapshot:{machine.machine_id}:{day_token}"

    cached = get_cache(cache_key)
    if cached:
        return cached

    result = calculate_snapshot(machine)

    set_cache(cache_key, result, CACHE_TTL_SNAPSHOT)

    return result


# ======================================
# SHIFTS (REAL-TIME)
# ======================================

@router.get("/shifts/{machine_key}")
def get_shifts(machine_key: str, db: Session = Depends(get_db)):

    machine = db.query(MachineConfig).filter(
        MachineConfig.machine_key == machine_key
    ).first()

    if not machine:
        return {"error": "Machine not found"}

    day_token = get_operational_day_token()
    cache_key = f"shifts:{machine.machine_id}:{day_token}"
 
    cached = get_cache(cache_key)
    if cached:
        return cached

    result = calculate_shift_data(machine)

    set_cache(cache_key, result, CACHE_TTL_SHIFTS)

    return result


# ======================================
# WEEKLY
# ======================================

@router.get("/weekly/{machine_key}")
def get_weekly(machine_key: str, db: Session = Depends(get_db)):

    machine = db.query(MachineConfig).filter(
        MachineConfig.machine_key == machine_key
    ).first()

    if not machine:
        return {"error": "Machine not found"}

    cache_key = f"weekly:{machine.machine_id}"

    cached = get_cache(cache_key)
    if cached:
        return cached

    today = datetime.now().date()

    for i in range(7):
        target_date = today - timedelta(days=i)
        calculate_and_store_daily(machine, target_date)

    records = (
        db.query(DailyProduction)
        .filter(DailyProduction.machine_id == machine.machine_id)
        .order_by(DailyProduction.date.desc())
        .limit(7)
        .all()
    )

    records = sorted(records, key=lambda x: x.date)

    result = {
        "dates": [r.date.strftime("%d-%b") for r in records],
        "production": [round(r.production_meters, 2) for r in records],
        "run_hours": [round(r.run_hours, 2) for r in records],
        "energy_kwh": [round(r.energy_kwh, 2) for r in records],
        "energy_per_meter": [round(r.energy_per_meter, 4) for r in records],
    }

    set_cache(cache_key, result, CACHE_TTL_WEEKLY)

    return result


# ======================================
# REPORT API — DAILY PRODUCTION (PostgreSQL)
# ======================================

def _resolve_machines(machine_key: Optional[str], db: Session):
    """
    Resolve machine_key → list of MachineConfig.
    If machine_key is empty or None, return ALL machines.
    """
    if machine_key:
        m = db.query(MachineConfig).filter(
            MachineConfig.machine_key == machine_key
        ).first()
        return [m] if m else []
    return db.query(MachineConfig).all()


def _machine_status_for_date(machine_id: int, target_date: date) -> str:
    """
    For historical dates: derive status from stored data.
    If run_hours == 0 → STOP, else RUN.
    For today: use live InfluxDB pulse check.
    """
    today = datetime.now().date()
    if target_date == today:
        return get_machine_status(machine_id)
    return None  # Will be derived from run_hours in the row


@router.get("/report/daily")
def report_daily(
    machine_key: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Returns today's daily production for selected machine(s).
    """
    machines = _resolve_machines(machine_key, db)
    if not machines:
        return {"rows": []}

    today = datetime.now().date()

    # Ensure today's record is computed
    for m in machines:
        calculate_and_store_daily(m, today)

    rows = []
    for m in machines:
        rec = db.query(DailyProduction).filter(
            DailyProduction.machine_id == m.machine_id,
            DailyProduction.date == today,
        ).first()

        if rec:
            status = get_machine_status(m.machine_id)
            rows.append({
                "date": rec.date.strftime("%d-%m-%Y"),
                "machine": m.machine_name,
                "run_hours": round(rec.run_hours, 1),
                "production_meters": round(rec.production_meters, 0),
                "energy_kwh": round(rec.energy_kwh, 1),
                "energy_per_meter": round(rec.energy_per_meter, 4),
                "status": status,
            })

    return {"rows": rows}


@router.get("/report/range")
def report_range(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    machine_key: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Returns daily production data for a date range from PostgreSQL.
    Computes & stores any missing days on the fly.
    """
    machines = _resolve_machines(machine_key, db)
    if not machines:
        return {"rows": []}

    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return {"error": "Invalid date format. Use YYYY-MM-DD."}

    if end_date < start_date:
        return {"error": "End date must be >= start date."}

    # Cap range to 90 days to prevent excessive queries
    if (end_date - start_date).days > 90:
        return {"error": "Date range cannot exceed 90 days."}

    today = datetime.now().date()

    # Compute & store any missing daily records within the range
    for m in machines:
        current = start_date
        while current <= end_date:
            # Only compute for dates up to today
            if current <= today:
                existing = db.query(DailyProduction).filter(
                    DailyProduction.machine_id == m.machine_id,
                    DailyProduction.date == current,
                ).first()
                if not existing:
                    calculate_and_store_daily(m, current)
            current += timedelta(days=1)

    # Now fetch all records in the range
    rows = []
    for m in machines:
        records = (
            db.query(DailyProduction)
            .filter(
                DailyProduction.machine_id == m.machine_id,
                DailyProduction.date >= start_date,
                DailyProduction.date <= end_date,
            )
            .order_by(DailyProduction.date)
            .all()
        )

        for rec in records:
            # Status: live for today, derived from run_hours for historical
            if rec.date == today:
                status = get_machine_status(m.machine_id)
            else:
                status = "RUN" if rec.run_hours > 0.5 else "STOP"

            rows.append({
                "date": rec.date.strftime("%d-%m-%Y"),
                "machine": m.machine_name,
                "run_hours": round(rec.run_hours, 1),
                "production_meters": round(rec.production_meters, 0),
                "energy_kwh": round(rec.energy_kwh, 1),
                "energy_per_meter": round(rec.energy_per_meter, 4),
                "status": status,
            })

    # Sort by date, then machine name
    rows.sort(key=lambda r: (r["date"], r["machine"]))

    return {"rows": rows}


@router.get("/report/shift-history")
def report_shift_history(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    machine_key: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Returns shift-level production data from PostgreSQL.
    """
    machines = _resolve_machines(machine_key, db)
    if not machines:
        return {"rows": []}

    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return {"error": "Invalid date format. Use YYYY-MM-DD."}

    rows = []
    for m in machines:
        records = (
            db.query(ShiftProduction)
            .filter(
                ShiftProduction.machine_id == m.machine_id,
                ShiftProduction.date >= start_date,
                ShiftProduction.date <= end_date,
            )
            .order_by(ShiftProduction.date, ShiftProduction.shift)
            .all()
        )

        for rec in records:
            rows.append({
                "date": rec.date.strftime("%d-%m-%Y"),
                "machine": m.machine_name,
                "shift": rec.shift,
                "run_hours": round(rec.run_hours, 1),
                "production_meters": round(rec.production_meters, 0),
                "energy_kwh": round(rec.energy_kwh, 1),
                "energy_per_meter": round(rec.energy_per_meter, 4),
                "machine_speed_mpm": round(rec.machine_speed_mpm or 0, 1),
            })

    rows.sort(key=lambda r: (r["date"], r["machine"], r["shift"]))

    return {"rows": rows}