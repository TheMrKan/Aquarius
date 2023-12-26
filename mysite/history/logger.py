from main.models import Controller, HistoryEntry
import json
from django.core.exceptions import ObjectDoesNotExist
import datetime
from typing import Dict, Any
import traceback


def log(controller_login: str, json_data: str):
    return
    print(f"Log: {json_data}")
    try:
        parsed: Dict[str, Any] = json.loads(json_data)
    except Exception:
        print("An error occured while parsing json log")
        traceback.print_exc()
        return

    try:
        controller = Controller.objects.get(mqtt_user=controller_login)
    except ObjectDoesNotExist:
        print(f"Failed to create a log entry: controller with prefix '{controller_login}' not found")
        return

    entry = get_entry(controller, parsed)
    entry.save()


def get_entry(controller: Controller, data: Dict[str, Any]) -> HistoryEntry:
    entry = HistoryEntry(controller=controller, log_time=datetime.datetime.now())

    if "AvrTime" in data.keys():
        try:
            hours, minutes = map(float, data["AvrTime"].replace(",", ".").split(":"))
            seconds = int(minutes % 1 * 60)
            minutes = int(minutes)
            avr_time = datetime.time(int(hours), minutes, seconds)
            entry.avr_time = avr_time
        except Exception:
            print(f"Failed to parse AvrTime: {data['AvrTime']}")
            traceback.print_exc()

    entry.cykl = data.get("Cykl", None)
    entry.channels_state = data.get("Chn", None)

    if "Sens" in data.keys():
        sensors: Dict[str, Any] = data["Sens"]

        entry.temp0 = sensors.get("Temp1", None)
        entry.temp1 = sensors.get("Temp2", None)
        entry.pressure = sensors.get("Press", None)
        entry.wspd = sensors.get("WSpd", None)
        entry.rain = sensors.get("Rain", None)
        entry.pause = sensors.get("Pau", None)
        entry.alarm = sensors.get("Alarm", None)
        entry.rssi = sensors.get("RSSI", None)

    return entry
