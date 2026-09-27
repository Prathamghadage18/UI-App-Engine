from sqlalchemy import Column, Integer, String, Float, Date, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from database import Base


class MachineConfig(Base):
    __tablename__ = "machine_config"

    id = Column(Integer, primary_key=True, index=True)

    machine_key = Column(String, unique=True, nullable=False)
    machine_id = Column(Integer, unique=True, nullable=False, index=True)

    machine_name = Column(String, nullable=False)
    location = Column(String, nullable=False)

    # ✅ Correct physics
    pulses_per_revolution = Column(Integer, nullable=False)
    meters_per_revolution = Column(Float, nullable=False)

    shift1_start = Column(String, nullable=False)
    shift1_end = Column(String, nullable=False)

    shift2_start = Column(String, nullable=False)
    shift2_end = Column(String, nullable=False)

    shift3_start = Column(String, nullable=False)
    shift3_end = Column(String, nullable=False)

    # relationships
    daily_records = relationship("DailyProduction", back_populates="machine", cascade="all, delete-orphan")
    shift_records = relationship("ShiftProduction", back_populates="machine", cascade="all, delete-orphan")
    hourly_records = relationship("HourlyProduction", back_populates="machine", cascade="all, delete-orphan")


# ===============================
# DAILY (already existing)
# ===============================
class DailyProduction(Base):
    __tablename__ = "daily_production"

    id = Column(Integer, primary_key=True, index=True)

    machine_id = Column(Integer, ForeignKey("machine_config.machine_id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)

    production_meters = Column(Float, nullable=False)
    run_hours = Column(Float, nullable=False)
    energy_kwh = Column(Float, nullable=False)
    energy_per_meter = Column(Float, nullable=False)

    machine = relationship("MachineConfig", back_populates="daily_records")

    __table_args__ = (
        UniqueConstraint("machine_id", "date", name="unique_machine_day"),
        Index("idx_machine_date", "machine_id", "date"),
    )


# ===============================
# 🟡 SHIFT LEVEL (NEW)
# ===============================
class ShiftProduction(Base):
    __tablename__ = "shift_production"

    id = Column(Integer, primary_key=True, index=True)

    machine_id = Column(Integer, ForeignKey("machine_config.machine_id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)

    shift = Column(String, nullable=False)  # Shift 1 / Shift 2 / Shift 3

    run_hours = Column(Float, nullable=False)
    production_meters = Column(Float, nullable=False)
    energy_kwh = Column(Float, nullable=False)
    energy_per_meter = Column(Float, nullable=False)
    machine_speed_mpm = Column(Float, nullable=True)

    machine = relationship("MachineConfig", back_populates="shift_records")

    __table_args__ = (
        UniqueConstraint("machine_id", "date", "shift", name="unique_machine_shift"),
        Index("idx_machine_shift", "machine_id", "date", "shift"),
    )


# ===============================
# 🔵 HOURLY LEVEL (NEW)
# ===============================
class HourlyProduction(Base):
    __tablename__ = "hourly_production"

    id = Column(Integer, primary_key=True, index=True)

    machine_id = Column(Integer, ForeignKey("machine_config.machine_id"), nullable=False, index=True)

    timestamp = Column(DateTime, nullable=False, index=True)  # hour bucket

    run_hours = Column(Float, nullable=False)
    production_meters = Column(Float, nullable=False)
    energy_kwh = Column(Float, nullable=False)
    energy_per_meter = Column(Float, nullable=False)

    machine = relationship("MachineConfig", back_populates="hourly_records")

    __table_args__ = (
        UniqueConstraint("machine_id", "timestamp", name="unique_machine_hour"),
        Index("idx_machine_hour", "machine_id", "timestamp"),
    )