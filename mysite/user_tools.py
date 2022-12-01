import json

import django.core.exceptions
from main.models import User, UserControllerPreferences, Controller, UserExtension

from typing import Dict, List, Union
from dataclasses import dataclass
from django.core.exceptions import ObjectDoesNotExist


def get_available_controllers(user: User) -> Dict[str, str]:
    """
    Возвращает сохраненные у пользователя контроллеры.\n
    Формат: {"mqtt_user": "verbous_name"}

    """

    try:
        saved_controllers: List[UserControllerPreferences] = user.userextension.usercontrollerpreferences_set.all()
    except ObjectDoesNotExist:
        userextension = UserExtension(user=user)
        userextension.save()
        return {}

    print("0:", saved_controllers)
    available_controllers = {}

    for cdata in saved_controllers:

        if cdata.mqtt_password == cdata.controller.mqtt_password:
            available_controllers[cdata.controller.mqtt_user] = cdata.verbous_name
        else:
            cdata.delete()

    return available_controllers


def add_controller(user: User, mqtt_user: str, password: str, verbous_name: str):
    try:
        saved_controllers: List[UserControllerPreferences] = user.userextension.usercontrollerpreferences_set.all()
    except ObjectDoesNotExist:
        userextension = UserExtension(user=user)
        userextension.save()

        saved_controllers = []

    for cdata in saved_controllers:
        if cdata.controller.mqtt_user == mqtt_user:
            cdata.mqtt_password = password
            cdata.verbous_name = verbous_name
            cdata.save()
            return

    print(Controller.objects.all())
    controller = Controller.objects.get(mqtt_user=mqtt_user)

    ucontprefs = UserControllerPreferences(user_extension=user.userextension,
                                           controller=controller,
                                           mqtt_password=password,
                                           verbous_name=verbous_name)
    ucontprefs.save()


def remove_controller(user: User, mqtt_user: str):
    try:
        ucontdata = user.userextension.usercontrollerpreferences_set.get(controller__mqtt_user=mqtt_user)
    except ObjectDoesNotExist:
        print("error")
        return

    ucontdata.delete()
    print("1:", get_available_controllers(user))

def is_authentificated(user: User, mqtt_user: str) -> bool:
    try:
        ucontdata = user.userextension.usercontrollerpreferences_set.get(controller__mqtt_user=mqtt_user)
    except ObjectDoesNotExist:
        return False

    return ucontdata.mqtt_password == ucontdata.controller.mqtt_password


def set_controller_name(user: User, mqtt_user: str, name: str):
    try:
        ucontdata = user.userextension.usercontrollerpreferences_set.get(controller__mqtt_user=mqtt_user)
    except ObjectDoesNotExist:
        return

    ucontdata.verbous_name = name
    ucontdata.save()


def get_controller_name(user: User, mqtt_user: str) -> str:
    try:
        ucontdata = user.userextension.usercontrollerpreferences_set.get(controller__mqtt_user=mqtt_user)
    except ObjectDoesNotExist:
        return "Контроллер"

    return ucontdata.verbous_name


