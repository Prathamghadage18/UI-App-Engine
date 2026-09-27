from sqlalchemy import text

from database import engine, Base
import models

print("Creating tables if they do not exist...")

Base.metadata.create_all(bind=engine)

# `create_all` does not alter tables that already exist. Keep existing
# PostgreSQL volumes compatible with newly added machine configuration fields.
with engine.begin() as connection:
	connection.execute(text(
		"ALTER TABLE machine_config "
		"ADD COLUMN IF NOT EXISTS pulses_per_revolution INTEGER NOT NULL DEFAULT 1"
	))
	connection.execute(text(
		"ALTER TABLE machine_config "
		"ADD COLUMN IF NOT EXISTS meters_per_revolution DOUBLE PRECISION NOT NULL DEFAULT 1.0"
	))

print("Database ready.")