# python3.6

import random,os
from paho.mqtt import client as mqtt_client
import celery.states as states
#from flask import Flask, Response
#from flask import url_for, jsonify
from worker import celery
import random, time

import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')


broker = os.environ['mqtthost']
port = int(os.environ['mqttport'])
topic = os.environ['mqtttopic']
username = os.environ['mqttuser']
password = os.environ['mqttpasswd']
#broker = '164.52.192.5'
#port = 1883
#topic = "GARWAREFILMS/CHILLER"
#username = 'sisai'
#password = 'sisai123'
# Generate a Client ID with the subscribe prefix.
client_id = f"ficus-subscribe-{random.randint(100, 900)}"
timeout = 2*60*60   # 1hrs

def connect_mqtt() -> mqtt_client:
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT Broker!")
        else:
            logger.info("Failed to connect, return code %d\n", rc)

    client = mqtt_client.Client(client_id)
    client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.connect(broker, port, keepalive=60)
    return client


def subscribe(client: mqtt_client):
    def on_message(client, userdata, msg):
        logger.info(f"topic:`{msg.topic}`, payload:`{msg.payload.decode()}`")
        task = celery.send_task('tasks.mqttfwdr', args=[msg.topic, msg.payload.decode()])
    
    client.subscribe(topic)
    client.on_message = on_message

def run():
    logger.info(f"broker:{broker}, port:{port}, uname:{username}, passwd: {password}, topic: {topic}")
    #client = connect_mqtt()
    #subscribe(client)
    #client.loop_forever()
    while True:
        logger.info(f"Creating MQTT client with client_id: {client_id}")

        client = connect_mqtt()
        subscribe(client)

        # Run MQTT loop for timeout seconds
        start_time = time.time()
        while time.time() - start_time < timeout:
            client.loop(timeout=1.0)

        logger.info("2 hours elapsed. Resetting client_id and MQTT connection...")
        client.disconnect()
        sys.exit(1)

if __name__ == '__main__':
    run()
