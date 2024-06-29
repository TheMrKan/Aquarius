import logging
import traceback

import django.db.models
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Controller, Channel, Program, UserExtension
from operator import add
from datetime import datetime, time, timedelta
import time
from ControllerManagers import ControllerV2Manager, LimitOfProgramsException, IncorrectCredentialsException
from main.consumers import ControllerConsumer
import json
import user_tools as utools
import dataclasses
import main.conf as conf
from main.utils import controller_instance_required, ensure_not_blocked

logger = logging.getLogger(__name__)

DAYS = {'monday': 'Понедельник',
        'tuesday': 'Вторник',
        'wednesday': 'Среда',
        'thursday': 'Четверг',
        'friday': 'Пятница',
        'saturday': 'Суббота',
        'sunday': 'Воскресенье'}


@login_required
def index(request):
    available_controllers = utools.get_available_controllers(request.user)

    status_message = 0
    if request.method == "POST":
        values = request.POST.dict()
        if all(k in values.keys() for k in ("user", "password")):
            if not any([i.mqtt_user == values["user"] for i in available_controllers]):    # исключаем возможность повторного добавления одного и того-же контроллера
                try:
                    if ControllerV2Manager.add(values["user"], values["password"]):
                        utools.add_controller(request.user, values["user"], values["password"], values.get("cname", f"Контроллер {values['user']}"))
                        available_controllers.append(utools.AvailableController(values["user"], values.get("cname", f"Контроллер {values['user']}"), values["password"]))
                        status_message = 1
                except IncorrectCredentialsException:
                    status_message = 2
                except Exception as ex:
                    logger.error("Failed to add new controller in the index view", exc_info=ex)
                    status_message = 0

    response = render(request, 'index.html',
                    {
                        'controllers': available_controllers,
                        'test_controller_name': conf.TEST_CONTROLLER_NAME,
                        'test_controller_mqtt_user': conf.TEST_CONTROLLER_USER,
                        'test_controller_mqtt_password': conf.TEST_CONTROLLER_PASSWORD,
                        'status_message': status_message
                    })

    return response


@login_required
def remove_controller(request, controller_username: str):
    utools.remove_controller(request.user, controller_username)

    return redirect("/")

@login_required
def reports(request):
    return render(request, 'reports.html')


@ensure_not_blocked
def pause(request, mqtt_user: str, controller_instance: ControllerV2Manager, minutes: int = -1):

    if minutes > -1:
        controller_instance.command_pause(minutes)
        controller_instance.command_get_state()
        return redirect("controller", mqtt_user=controller_instance.user)

    return render(request,
                  "pause_activation.html",
                  {
                      "mqtt_user": controller_instance.user,
                      "cont": controller_instance.data_model,
                  })


@ensure_not_blocked
def manual_activation(request, mqtt_user: str, controller_instance: ControllerV2Manager, chn, minutes=-1):
    chn = int(chn)

    channel = Channel.objects.filter(controller__mqtt_user=controller_instance.user, number=chn)
    if len(channel) > 0:
        channel = channel[0]
    else:
        return redirect("/")

    if minutes > -1:
        controller_instance.command_turn_on_channel(chn, minutes)
        controller_instance.command_get_state()
        return redirect("controller", mqtt_user=controller_instance.user)

    return render(request,
                  "manual_activation.html",
                  {
                      "mqtt_user": controller_instance.user,
                      "cont": controller_instance.data_model,
                      "chn": chn,
                  })


@ensure_not_blocked
def manual_activation_selector(request, mqtt_user: str, controller_instance: ControllerV2Manager, turn_off_all=False):

    channels = controller_instance.data_model.channels

    hide_channels_selector: bool = controller_instance.data_model.version < 200

    controller_instance.command_get_state()
    if turn_off_all:
        if controller_instance is not None:
            controller_instance.turn_off_all_channels()
            controller_instance.command_get_state()
            return redirect("controller", mqtt_user=controller_instance.user)

    return render(request,
                  "manual_activation_selector.html",
                  {
                      "mqtt_user": controller_instance.user,
                      'channels_state_json': json.dumps([i.state for i in channels]),
                      'channels_names_json': json.dumps([i.name for i in channels]),
                      "cont": controller_instance.data_model,
                      "hide_channels_selector": hide_channels_selector
                  })

@ensure_not_blocked
def channel_naming(request, mqtt_user: str, controller_instance: ControllerV2Manager):

    channels = controller_instance.data_model.channels

    hide_channels_selector: bool = controller_instance.data_model.version < 200

    if request.method == "POST":
        data = request.POST.dict()
        for k in data.keys():
            if k.startswith("chn") and k.endswith("_name"):
                channel_number = int(k.replace("chn", "").replace("_name", ""))
                channel = channels.get(number=channel_number)
                if channel.name != data[f"chn{channel_number}_name"]:
                    channel.name = data[f"chn{channel_number}_name"]
                    channel.save()
        return redirect("controller", controller_instance.user)

    return render(request, "channel_naming.html", {
        "cont": controller_instance.data_model,
        "mqtt_user": controller_instance.user,
        "channels_names_json": [i.name for i in channels],
        "hide_channels_selector": hide_channels_selector
    })

@controller_instance_required
def controller(request, mqtt_user: str, controller_instance: ControllerV2Manager):

    if request.method == "POST":
        if "set_time" in request.POST.dict().keys():
            received_time = request.POST.dict()["set_time"].split("-")
            controller_instance.command_set_time(*[int(i) for i in received_time])

    cont = controller_instance.data_model
    programs = Program.objects.filter(channel__controller__mqtt_user=controller_instance.user)
    channels = cont.channels

    hide_humidity = cont.version < 200
    hide_channels_selector: bool = cont.version < 200
    hidden_channel: str = "" if not hide_channels_selector or not controller_instance.get_pump_state() \
        else str(controller_instance.pump_channel_number)

    day = list(DAYS.values())[cont.day - 1] if cont.day <= len(DAYS) else "Ошибка"
    return render(request, 'controller.html',
                  {
                      'mqtt_user': controller_instance.user,
                      'cont': cont,
                      'day': day,
                      'channels_state_json': json.dumps([chn.state for chn in channels]),
                      'channels_names_json': json.dumps([chn.name for chn in channels]),
                      "hide_channels_selector": hide_channels_selector,
                      "hide_humidity": hide_humidity,
                      "hidden_channel": hidden_channel,
                      "name": utools.get_controller_name(request.user, controller_instance.user)
                    })


@ensure_not_blocked
def program(request, mqtt_user: str, controller_instance: ControllerV2Manager, chn, prg_id):

    program = Program.objects.get(id=prg_id)
    weeks = program.get_weeks()

    if request.method == 'POST':
        data: dict = request.POST.dict()

        if data.get("delete_prg", "False") == "True":
            controller_instance.remove_program(program.channel.number, program.id)
            return redirect("channel", controller_instance.user, chn)

        days = "".join([str(i) for i in range(1, 8) if f"wd{i}" in data.keys()])
        weeks = ("even" in data.keys(), "odd" in data.keys())
        hour = int(data["prog_time"][:2]) if data["prog_time"][:2].isdigit() else 0
        minute = int(data["prog_time"][3:5]) if data["prog_time"][:2].isdigit() else 0
        t_min = int(data["prog_cmin"])
        t_max = int(data["prog_cmax"])

        controller_instance.edit_or_add_program(chn, prg_id, days, weeks, hour, minute, t_min, t_max)
        return redirect("channel", controller_instance.user, chn)

    return render(request, "setup_wdays.html",
                  {
                      "mqtt_user": controller_instance.user,
                      "chn": chn,
                      "prg_id": prg_id,
                      "time": f"{program.hour:02}:{program.minute:02}",
                      "t_min": program.t_min,
                      "t_max": program.t_max,
                      "d1": "1" in program.days,
                      "d2": "2" in program.days,
                      "d3": "3" in program.days,
                      "d4": "4" in program.days,
                      "d5": "5" in program.days,
                      "d6": "6" in program.days,
                      "d7": "7" in program.days,
                      "even_week": weeks[0],
                      "odd_week": weeks[1]
                  })


@ensure_not_blocked
def pump(request, mqtt_user: str, controller_instance: ControllerV2Manager):

    if request.method == "POST":
        data = request.POST.dict()
        if all([k in data.keys() for k in ("pmin", "pmax", "vmin", "vmax")]):
            try:
                controller_instance.configure_pump(float(data["pmin"]) * 10, float(data["pmax"]) * 10, float(data["vmin"]), float(data["vmax"]))
            except ValueError:
                pass
        return redirect("controller", controller_instance.user)

    pmin, pmax, vmin, vmax = controller_instance.get_pump_settings()

    return render(request, "pump.html",
                  {
                      "mqtt_user": controller_instance.user,
                      "pmin": "{0:.1f}".format(pmin / 10).replace(",", "."),
                      "pmax": "{0:.1f}".format(pmax / 10).replace(",", "."),
                      "vmin": str(vmin).replace(",", "."),
                      "vmax": str(vmax).replace(",", ".")
                  })


@ensure_not_blocked
def remote_blocks(request, mqtt_user: str, controller_instance: ControllerV2Manager):

    if request.method == "POST":
        data = request.POST.dict()
        if all([k in data.keys() for k in ("block0", "block1", "block2")]):
            try:
                controller_instance.set_remote_blocks(int(data["block0"]), int(data["block1"]), int(data["block2"]))
            except ValueError:
                pass
        return redirect("controller", controller_instance.user)

    rblocks = controller_instance.get_remote_blocks()

    return render(request, "remote_blocks.html",
                  {
                      "mqtt_user": controller_instance.user,
                      "block0": rblocks[0],
                      "block1": rblocks[1],
                      "block2": rblocks[2]
                  })


@ensure_not_blocked
def channel(request, mqtt_user: str, controller_instance: ControllerV2Manager, chn, create_prg=False):

    class PrgData:
        id = 0
        header = ""
        days = []
        weeks = ()
        t_start_hour = 0
        t_start_minute = 0
        t_min = 0
        t_max = 0

        def toDict(self):
            return {
                "id": self.id,
                "days": self.days,
                "weeks": self.weeks,
                "t_start_hour": self.t_start_hour,
                "t_start_minute": self.t_start_minute,
                "t_min": self.t_min,
                "t_max": self.t_max,
            }

        def __init__(self, id, days, hour, minute, even_week, odd_week, t_min, t_max):
            self.id = id
            self.days = days
            self.weeks = [even_week, odd_week]
            self.t_start_hour = hour
            self.t_start_minute = minute
            self.t_min = t_min
            self.t_max = t_max

    if create_prg:
        logger.debug(f"Trying to create new program for controller {controller_instance.user} on channel {chn}...")
        try:
            new_prg: Program = controller_instance.create_program(chn)
            logger.info(f"Successfully created new program for controller {controller_instance.user} on channel {chn}. ID: {new_prg.id}")
        except LimitOfProgramsException:
            logger.info(f"Failed to create new program for controller {controller_instance.user} on channel {chn}: programs limit exceed")
            return redirect("channel", controller_instance.user, chn)
        return redirect("program", controller_instance.user, chn, new_prg.id)

    chan: Channel = Channel.objects.get(controller__mqtt_user=controller_instance.user, number=chn)
    programs = Program.objects.filter(channel=chan)

    prgs = []
    for pr in programs:
        prgs.append(PrgData(pr.id, pr.days, pr.hour, pr.minute, *pr.get_weeks(), pr.t_min, pr.t_max))

    if request.method == 'POST':
        data = request.POST.dict()
        chan.season = int(data["seasonpc"]) if data["seasonpc"].isdigit() else 100
        chan.temp_min = int(data["cmindeg"]) if data["cmindeg"] else chan.temp_min
        chan.temp_max = int(data["cmaxdeg"]) if data["cmaxdeg"] else chan.temp_max
        chan.meandr_on = int(data["meandr_on"]) if data["meandr_on"] else chan.meandr_on
        chan.meaoff_cmin = int(data["meaoff_cmin"]) if data["meaoff_cmin"] else chan.meaoff_cmin
        chan.meaoff_cmax = int(data["meaoff_cmax"]) if data["meaoff_cmax"] else chan.meaoff_cmax
        chan.press_on = float(data["press_on"]) * 10
        chan.press_off = float(data["press_off"]) * 10
        chan.lowlevel = "lowlevel" in data.keys()
        chan.rainsens = True if data["rainsens"] == '1' else False
        chan.tempsens = int(data["tempsens"])
        chan.save()
        controller_instance.command_send_channel(chan.number)
        return redirect("controller", controller_instance.user)

    return render(request, 'channel.html',
                  {
                      'mqtt_user': controller_instance.user,
                      'chn': int(chn),
                      'prgs': prgs,
                      'prg_data_json': json.dumps([i.toDict() for i in prgs]),
                      'cont': controller_instance.data_model,
                      'chan': chan,
                   })


def gantt(request, mqtt_user: str):

    @dataclasses.dataclass
    class Hour:
        chn: int
        prg: int
        active: bool

    def get_day(start, l, chn_num: int, prg_num: int):
        out = []
        for i in range(24):
            if start <= i < (start + l):
                out.append(Hour(chn_num, prg_num, True))
            else:
                out.append(Hour(chn_num, prg_num, False))
        return out

    def get_h_len(t_max):
        l = t_max // 60
        if t_max % 60 > 0:
            l += 1
        return l

    def get_week(chn, week):
        week_bit_mask = 2 if week == 0 else 1    # '10' or '01'
        prgs = Program.objects.filter(channel=chn)
        out = []
        for i in range(7):
            out.append([])
            for j in range(24):
                out[i].append(Hour(0, 0, False))
        for p in prgs:
            if p.weeks & week_bit_mask:
                days = list(p.days)
                for d in days:
                    for i, h in enumerate(get_day(p.hour, get_h_len(p.t_max), chn.number, p.id)):
                        if not out[int(d) - 1][i].active:
                            out[int(d) - 1][i] = h
        return out

    controller = Controller.objects.get(mqtt_user=mqtt_user)
    channels = controller.channels

    if controller.version < 200:
        channels = channels[:10]

    lines = []
    for chn in channels:
        lines.append(get_week(chn, 0) + get_week(chn, 1))

    return render(request, 'gantt.html',
                  {
                      'mqtt_user': mqtt_user,
                      'lines_week': lines,
                      'day_of_week': datetime.now().weekday()
                   })


def history(request):
    return render(request, "history.html", {})
