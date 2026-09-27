#!/bin/sh

echo "Starting FastAPI..."

uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2 &

APP_PID=$!

echo "Starting Scheduler..."

python -m utils.scheduler_runner &

SCHED_PID=$!

echo "Waiting for API..."

until curl -s http://localhost:8000/api/health > /dev/null
do
  sleep 2
done

echo "Initializing machines..."

curl -X POST http://localhost:8000/api/init-machines

echo "Machines initialized"

# Wait for both processes
wait $APP_PID
wait $SCHED_PID