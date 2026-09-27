# python3.6
from typing import Any

from flask import Flask, jsonify, request, url_for
# import pandas as pd
# from worker import celery
import random, time

import os
from celery import Celery, states

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379'),
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379')

celery = Celery('tasks', broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)

app = Flask(__name__)


@app.route('/tonnage', methods=['GET'])
def calculate_tonnage():
    minutes = int(request.args.get('minutes', 10))
    logger.info(f"calculate tonnage for {minutes} minutes")
    task = celery.send_task('tasks.tonnage', args=[minutes], kwargs={})
    # response = f"<a href='{url_for('check_task', task_id=task.id, external=True)}'> check status of {task.id} </a>"
    return jsonify({"id": task.id})

@app.route('/check/<string:task_id>')
def check_task(task_id: str) -> str:
    res = celery.AsyncResult(task_id)
    if res.state == states.PENDING:
        return res.state
    else:
        return str(res.result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)