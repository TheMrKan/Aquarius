from __future__ import annotations
import datetime
import time
from bitstring import BitStream, BitArray
import traceback

import paho.mqtt.client as MQTT
import random

def _int(i):
    try:
        return int(i)
    except:
        return 0

class MQTTManager:

    client = None
    onConnected = None
    topicHandlers = {}
    connected = False
    trying = 2
    incorrect_credentials: bool

    def send(self, topic, data, retain=False):
        if self.client is None:
            return
        print(f"MQTT ({self.host}:{self.port}@{self.user}): Send to [{topic}]: {data}")
        self.client.publish(self.prefix + topic, data, retain=retain)

    def on_disconnect(self, *args):
        self.client.on_message = lambda: True

    def subscribe(self, topic, func):
        self.topicHandlers[topic] = func
        self.client.subscribe(self.prefix + topic)

    def unsubscribe(self, topic):
        if topic in self.topicHandlers.keys():
            del self.topicHandlers[topic]
        self.client.unsubscribe(self.prefix + topic)

    def on_connected(self, client, userdata, flags, rc):
        # rc = 0 - подключено
        # rc = 5 - неправильный логин или пароль
        if self.trying > 0:
            self.trying -= 1
        else:
            return False
        print(client, userdata, flags, rc)
        if rc == 0:
            print(f'MQTT: Connected to {self.user}@{self.host}:{self.port}')
            # from main.models import Controller, Channel, Program
            if self.onConnected is not None:
                self.onConnected(self)
            self.connected = True
            self.trying = 0
            return True
        else:
            self.incorrect_credentials = rc == 5
            self.connected = False
            return False

    def connect(self):
        self.client = MQTT.Client()
        self.client.username_pw_set(self.user, self.password)
        self.client.on_message = lambda cl, userdata, message: self.on_message(userdata, message)
        self.client.on_connect = self.on_connected
        self.client.connect(self.host, port=self.port, keepalive=15)
        self.client.loop_start()
        while self.trying > 0:
            pass
        return self.connected

    def disconnect(self):
        self.client.disconnect()
        self.topicHandlers.clear()
        del self.client


    def on_message(self, userdata, message):
        print(f'MQTT ({self.user}) - [{message.topic.replace(self.prefix, "")}] - {str(message.payload.decode("utf-8")).strip()}')
        if message.topic.replace(self.prefix, '') in self.topicHandlers.keys():
            #print("Handle:", str(message.payload.decode("utf-8")).strip())
            self.topicHandlers[message.topic.replace(self.prefix, "")](self, self.user, str(message.payload.decode("utf-8")).strip())

    def __init__(self, host, port, user, password, prefix):
        self.topicHandlers = {}
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.prefix = prefix
        self.incorrect_credentials = False

    @staticmethod
    def try_connect(host: str, port: int, user: str, password: str, prefix: str) -> tuple[MQTTManager | None, bool]:
        try:
            port = int(port)
            m = MQTTManager(host, port, user, password, prefix)
            s = m.connect()
            return (m, False) if s else (None, m.incorrect_credentials)
        except Exception as ex:
            traceback.print_exc()
            return None, False


def test():
    manager = MQTTManager("hd.tlt.ru", 18883, "21E", "180690033", "21E/")
    manager.connect()


    manager.client.loop_forever()

if __name__ == "__main__":
    test()