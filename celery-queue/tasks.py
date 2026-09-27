import os
import time, json
from typing import List, Dict, Any

from celery import Celery
import logging, re, traceback
from influxdb import InfluxDBClient
import urllib3
from datetime import datetime
import pytz
import time

urllib3.disable_warnings()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379'),
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379')
celery = Celery('tasks', broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)

INFLUXDB_ADDRESS = os.environ.get('INFLUXDB_URL')
INFLUXDB_USER = os.environ.get('INFLUXDB_USER',"admin")
INFLUXDB_PASSWORD = os.environ.get('INFLUXDB_PASSWORD', "admin123")
INFLUXDB_DATABASE = os.environ.get('INFLUXDB_DATABASE')
MQTT_REGEX = INFLUXDB_DATABASE + '/([^/]+)'
tz = pytz.timezone('Asia/Kolkata')
PLUGINS = os.environ.get('PLUGINS','[]')
PLUGINS = json.loads(PLUGINS)

# defs amd constants #
root_3 = 1.73205080757
cosPHI = 0.96
MF = 0.1

influxdb_client = InfluxDBClient(INFLUXDB_ADDRESS, 8086, INFLUXDB_USER, INFLUXDB_PASSWORD, None, ssl=False,
                                 verify_ssl=False)


def _init_influxdb_database(dbname):
    databases = influxdb_client.get_list_database()
    if len(list(filter(lambda x: x['name'] == dbname, databases))) == 0:
        influxdb_client.create_database(dbname)
    influxdb_client.switch_database(dbname)


# @celery.task(name='tasks.chiller')
# def dumpchiller(topic: str, payload: str) -> None:
#     logger.info(f"topic: {topic}, payload: {payload}")
#     influx_body = parsepayload("chiller", payload)
#     if influx_body:
#         influx_write(influx_body)
#
# @celery.task(name='tasks.flowmeter')
# def dumpflowmeter(topic: str, payload: str) -> None:
#     logger.info(f"topic: {topic}, payload: {payload}")
#     influx_body = parsepayload("flowmeter", payload)
#     if influx_body:
#         influx_write(influx_body)
# @celery.task(name='tasks.level')
# def dumplevel(topic: str, payload: str) -> None:
#     logger.info(f"topic: {topic}, payload: {payload}")
#
# @celery.task(name='tasks.energy')
# def dumpenergy(topic: str, payload: str) -> None:
#     logger.info(f"topic: {topic}, payload: {payload}")
#
# @celery.task(name='tasks.plc')
# def dumpplc(topic: str, payload: str) -> None:
#     logger.info(f"topic: {topic}, payload: {payload}")
#
# @celery.task(name='tasks.tonnage')
# def tonnage(*args, **kwargs) -> Any:
#     logger.info(f"I'm in task.tonnage args: {args}, kwargs: {kwargs}")
#     return args, kwargs


@celery.task(name='tasks.mqttfwdr')
def dbdumper(topic: str, payload: str) -> None:
    logger.info(f"topic: {topic}, payload: {payload}")
    gwid = topic.strip('/').split('/')[2]
    db = topic.strip('/').split('/')[0]
#    if db == 'Org_Garware':
#        db = "CHILLER"
    if db not in PLUGINS:
        logger.error(f"ERROR: PLUGINS or TOPIC should be {PLUGINS}")
        return
    # Check if the gateway ID is a valid 12-character hex string
    if not re.fullmatch(r'[0-9a-fA-F]{12}', gwid):
        logger.error(f"Invalid gateway ID: {gwid}, should be 12digit alphanumeric")
        raise Exception(f"Invalid gateway ID: {gwid}, should be 12digit alphanumeric")

    influx_body = parsepayload(gwid, payload)
    if influx_body:
        influx_write(db, influx_body) #uncomment it actual db write
        #influx_write("Org_SISAI", influx_body)


def influx_write(dbname: str, body: list):
    _init_influxdb_database(dbname)
    try:
        logger.info(f"->[PUSH-to-db]:{dbname}, body:{body}")
        influxdb_client.write_points(body)  # influx db insert
    except Exception as e:
        logger.error(f"json -> influxdb push error, no modbus data  {e.args}")
        traceback.print_exc()
    return


def parsepayload(measurement: str, payload: str):
    body = list()
    tags = dict()
    fields = dict()

    def zeroOnnegative(val):
        return 0.0 if val <= 0 else val * 1.0

    def parsefield() -> dict:
        data = dict()
        try:
            data = json.loads(payload)
            return data
        except Exception as e:
            logger.error(f"payload -> json error, {e.args}")
        return None

    _fields = parsefield()
    if _fields is None:
        return
    if "ERROR" in _fields.keys():
        logger.critical(
            f"GW-ERROR: \"{_fields['ERROR']}\", DATA not pushed to db.Follow MQTT msgs for deviceID \"{_fields['deviceID']}\"")
        return
    logger.info(f"Begin to process data upon gatewayID: {measurement}, {_fields}")
    _tags = ["location", "name", "deviceID", "ip", "mac", "simnumber", "operator"]
    for t in _tags:
        try:
            tags[t] = _fields[t]
        except Exception as e:
            logger.warning(f"field:{t} not found, assigning defaut value")
            tags[t] = "NOT_FOUND"
    if "modbus" not in _fields.keys():
        logger.warning(
            f"GW-ERROR: payload does not contain key \"modbus\", Follow MQTT msgs for deviceID \"{_fields['deviceID']}\"")
    else:
        fields = _fields['modbus'][0]
    # Also mention id as tag
    try:
        tags["id"] = fields["id"]
        del (fields["id"])
    except:
        logger.info("id is not removed")

#    # Define the allowed field keys once
#    field_keys = ["AI1", "AI2", "DI1", "DI2", "DI3", "DI4", "DI5", "DI6", "DO1", "DO2"]
#
#    # Copy only the allowed keys present in _fields
#    fields = {k: _fields[k] for k in field_keys if k in _fields}
#
    # Handle error condition
    if "ERROR" in fields:
        logger.info("RS485 COMM ERROR")
        #fields = {}
        #fields = {"RS485": "COMM_ERROR"}
    if "AI1" in _fields:
        fields["AI1"] = _fields["AI1"]
    if "AI2" in _fields:
        fields["AI2"] = _fields["AI2"]
    if "AI3" in _fields:
        fields["AI3"] = _fields["AI3"]
    if "AI4" in _fields:
        fields["AI4"] = _fields["AI4"]
    if "DI1" in _fields:
        fields["DI1"] = _fields["DI1"]
    if "DI2" in _fields:
        fields["DI2"] = _fields["DI2"]
    if "DI3" in _fields:
        fields["DI3"] = _fields["DI3"]
    if "DI4" in _fields:
        fields["DI4"] = _fields["DI4"]
    if "DI5" in _fields:
        fields["DI5"] = _fields["DI5"]
    if "DI6" in _fields:
        fields["DI6"] = _fields["DI6"]
    if "DO1" in _fields:
        fields["DO1"] = _fields["DO1"]
    if "DO2" in _fields:
        fields["DO2"] = _fields["DO2"]
#    if "sigQ" in _fields:
#        fields["sigq"] = _fields["sigQ"]
    if "ERROR" in fields.keys():
        logger.info("RS485 COMM ERROR")
        del fields["ERROR"]
        #fields = {}
    for key in fields.keys():
        try:
            fields[key] = fields[key]
        except:
            pass
            #fields[key] = None
    #    t = datetime.fromtimestamp(_fields["timestamp"]-19800, tz=tz).isoformat()
    t = datetime.fromtimestamp(time.time().__int__(), tz=tz).isoformat()

    m = dict()
    m["fields"] = fields
    m["tags"] = tags
    m["measurement"] = measurement
    m["time"] = t
    body.append(m)
    return body

# _init_influxdb_database(INFLUXDB_DATABASE)
