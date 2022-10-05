import django.db.models
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Controller, Channel, Program, UserExtension
from operator import add
from datetime import datetime, time, timedelta
import time
from ControllerManagers import ControllerV2Manager
from main.consumers import ControllerConsumer
import json

DAYS = {'monday': 'Понедельник',
        'tuesday': 'Вторник',
        'wednesday': 'Среда',
        'thursday': 'Четверг',
        'friday': 'Пятница',
        'saturday': 'Суббота',
        'sunday': 'Воскресенье'}

@login_required
def index(request):
    try:
        saved_controllers = request.user.userextension.saved_controllers
    except:
        uex = UserExtension(user=request.user, saved_controllers="[]")
        uex.save()
        saved_controllers = "[]"
    if saved_controllers is None:
        saved_controllers = []
    else:
        saved_controllers = json.loads(saved_controllers)
    if request.method == "POST":
        values = request.POST.dict()
        if all(k in values.keys() for k in ("server", "port", "user", "password", "prefix")):

            if not [True for c in saved_controllers if c[0] == values["user"]]:    # исключаем возможность повторного добавления одного и того-же контроллера
                print({k: values[k] for k in ["cname", "email"] if k in values.keys()})
                if ControllerV2Manager.add(values["user"], values["password"],
                                           host=values["server"], port=int(values["port"]), prefix=values["prefix"],
                                           **{k: values[k] for k in ["cname", "email"] if k in values.keys()}):
                    saved_controllers.append([values["user"], values["password"]])
    controllers = []
    _remove = []
    for c in saved_controllers:
        if ControllerV2Manager.check_auth(c[0], c[1]):
            controllers.append(ControllerV2Manager.get_instance(c[0]).data_model)
        else:
            _remove.append(c)
    [saved_controllers.remove(c) for c in _remove]
    response = render(request, 'main/index.html',
                    {
                        'controllers': controllers
                    })

    request.user.userextension.saved_controllers = json.dumps(saved_controllers)
    request.user.userextension.save()
    return response

@login_required
def reports(request):
    return render(request, 'main/reports.html')

@login_required
def pause(request, mqtt_user, minutes: int = -1):
    if not ControllerV2Manager.check_auth(mqtt_user=mqtt_user, user=request.user):
        return redirect("/")
    if ControllerV2Manager.check_block(mqtt_user):
        return redirect("controller", mqtt_user)

    cont = Controller.objects.get(mqtt_user=mqtt_user)
    instance: ControllerV2Manager = ControllerV2Manager.get_instance(mqtt_user)

    if minutes > -1:
        instance.command_pause(minutes)
        instance.command_get_state()
        return redirect("controller", mqtt_user=mqtt_user)

    return render(request,
                  "main/pause_activation.html",
                  {
                      "mqtt_user": mqtt_user,
                      "cont": cont,
                  })


@login_required
def manual_activation(request, mqtt_user, chn, minutes=-1):
    if not ControllerV2Manager.check_auth(mqtt_user=mqtt_user, user=request.user):
        return redirect("/")
    if ControllerV2Manager.check_block(mqtt_user):
        return redirect("controller", mqtt_user)

    chn = int(chn)

    channel = Channel.objects.filter(controller__mqtt_user=mqtt_user, number=chn)
    if len(channel) > 0:
        channel = channel[0]
    else:
        return redirect("/")
    cont = Controller.objects.get(mqtt_user=mqtt_user)
    instance: ControllerV2Manager = ControllerV2Manager.get_instance(mqtt_user)

    if minutes > -1:
        instance.command_turn_on_channel(chn, minutes)
        instance.command_get_state()
        return redirect("controller", mqtt_user=mqtt_user)

    return render(request,
                  "main/manual_activation.html",
                  {
                      "mqtt_user": mqtt_user,
                      "cont": cont,
                      "chn": chn,
                  })


@login_required
def manual_activation_selector(request, mqtt_user, turn_off_all=False):
    if not ControllerV2Manager.check_auth(mqtt_user=mqtt_user, user=request.user):
        return redirect("/")
    if ControllerV2Manager.check_block(mqtt_user):
        return redirect("controller", mqtt_user)

    channels = Channel.objects.filter(controller__mqtt_user=mqtt_user)
    cont = Controller.objects.get(mqtt_user=mqtt_user)

    instance: ControllerV2Manager = ControllerV2Manager.get_instance(mqtt_user)
    instance.command_get_state()
    if turn_off_all:
        if instance is not None:
            instance.turn_off_all_channels()
            instance.command_get_state()
            return redirect("controller", mqtt_user=mqtt_user)

    return render(request,
                  "main/manual_activation_selector.html",
                  {
                      "mqtt_user": mqtt_user,
                      'channels_state_json': json.dumps([i.state for i in channels]),
                      'channels_names_json': json.dumps([i.name for i in channels]),
                      "cont": cont,
                  })

@login_required
def channel_naming(request, mqtt_user):
    if not ControllerV2Manager.check_auth(mqtt_user=mqtt_user, user=request.user):
        return redirect("/")
    if ControllerV2Manager.check_block(mqtt_user):
        return redirect("controller", mqtt_user)

    controller: Controller = Controller.objects.get(mqtt_user=mqtt_user)
    channels = Channel.objects.filter(controller=controller)

    if request.method == "POST":
        data = request.POST.dict()
        for k in data.keys():
            if k.startswith("chn") and k.endswith("_name"):
                channel_number = int(k.replace("chn", "").replace("_name", ""))
                channel = channels.get(number=channel_number)
                if channel.name != data[f"chn{channel_number}_name"]:
                    channel.name = data[f"chn{channel_number}_name"]
                    channel.save()
        return redirect("controller", mqtt_user)

    return render(request, "main/channel_naming.html", {
        "cont": controller,
        "mqtt_user": mqtt_user,
        "channels_names_json": [i.name for i in channels]
    })

@login_required
def controller(request, mqtt_user):
    if not ControllerV2Manager.check_auth(mqtt_user=mqtt_user, user=request.user):
        return redirect("/")


    def get_day(start, l):
        out = []
        for i in range(24):
            if start <= i < (start + l):
                out.append(1)
            else:
                out.append(0)
        return out

    def get_h_len(t_max):
        l = t_max // 60
        if t_max % 60 > 0:
            l += 1
        return l

    def get_week(chn):
        prgs = Program.objects.filter(channel=chn)
        out = []
        for i in range(7):
            out.append([])
            for j in range(24):
                out[i].append(0)
        for p in prgs:
            days = list(p.days)
            for d in days:
                for i, h in enumerate(get_day(p.hour, get_h_len(p.t_max))):
                    if out[int(d) - 1][i] == 0:
                        out[int(d) - 1][i] += h

        return out

    instance = ControllerV2Manager.get_instance(mqtt_user)
    if instance is not None:
        instance.command_get_state()

    if request.method == "POST":
        if "set_time" in request.POST.dict().keys():
            received_time = request.POST.dict()["set_time"].split("-")
            instance.command_set_time(*[int(i) for i in received_time])

    programs = Program.objects.filter(channel__controller__mqtt_user=mqtt_user)
    channels = Channel.objects.filter(controller__mqtt_user=mqtt_user)
    cont = Controller.objects.get(mqtt_user=mqtt_user)

    hide_channels_selector: bool = cont.version < 200
    hidden_channel: str = "" if hide_channels_selector and not instance.get_pump_state() \
        else str(instance.pump_channel_number)

    class Line:
        def __init__(self, name, status, data):
            self.status = status
            self.name = name
            self.data = data

    lines = []
    for chn in channels:
        lines.append(Line(chn.name, chn.state, get_week(chn)))

    return render(request, 'main/controller.html',
                  {
                      'mqtt_user': mqtt_user,
                      'lines_week': lines,
                      'cont': cont,
                      'day': list(DAYS.values())[cont.day-1],
                      'channels_state_json': json.dumps([i.status for i in lines]),
                      'channels_names_json': json.dumps([i.name for i in lines]),
                      "hide_channels_selector": hide_channels_selector,
                      "hidden_channel": hidden_channel
                    })

@login_required
def controller_day(request, mqtt_user, day):
    if not ControllerV2Manager.check_auth(mqtt_user=mqtt_user, user=request.user):
        return redirect("/")
    def get_m(t):
        out = t // 2
        if t % 2 > 0:
            out += 1
        return out

    def get_time(h, m, t):
        start = [h, get_m(m)]
        stop = [h + t // 60, get_m((m + t % 60) % 60)]
        stop[0] += (m + t % 60) // 60
        return start, stop

    channels = Channel.objects.filter(controller__mqtt_user=mqtt_user)
    lines = []
    for i in range(len(channels)):
        lines.append([])
        for j in range(24):
            lines[i].append([])
            for g in range(30):
                lines[i][j].append(0)
    day_num = list(DAYS.keys()).index(day) + 1
    programs = Program.objects.filter(channel__controller__mqtt_user=mqtt_user, days__contains=str(day_num))


    for p in programs:
        start, stop = get_time(p.hour, p.minute, p.t_max)
        if (p.minute + (p.t_max % 60)) % 2 > 0:
            stop[1] += 1
        for h in range(0, 24):
            for m in range(0, 30):
                if h == start[0] and m >= start[1] and not start[0] == stop[0]:
                    if lines[p.channel.id-1][h][m] == 0:
                        lines[p.channel.id-1][h][m] = 1
                elif start[0] < h < stop[0]:
                    if lines[p.channel.id-1][h][m] == 0:
                        lines[p.channel.id-1][h][m] = 1
                elif h == stop[0] and m <= stop[1]:
                    if lines[p.channel.id-1][h][m] == 0:
                        lines[p.channel.id-1][h][m] = 1

    return render(request, 'main/controller_day.html',
                  {
                      'mqtt_user': mqtt_user,
                      'day': DAYS[day],
                      'hours_total': [i for i in range(24)],
                      'lines_day': lines
                   })

@login_required()
def channels(request, mqtt_user):
    if not ControllerV2Manager.check_auth(mqtt_user=mqtt_user, user=request.user):
        return redirect("/")

    channels = Channel.objects.filter(controller__mqtt_user=mqtt_user)

@login_required()
def program(request, mqtt_user, chn, prg_num):
    if not ControllerV2Manager.check_auth(mqtt_user=mqtt_user, user=request.user):
        return redirect("/")
    if ControllerV2Manager.check_block(mqtt_user):
        return redirect("controller", mqtt_user)

    instance = ControllerV2Manager.get_instance(mqtt_user)
    program = Program.objects.get(channel__controller__mqtt_user=mqtt_user, channel__number=chn, number=prg_num)
    weeks = program.get_weeks()

    if request.method == 'POST':
        data = request.POST.dict()
        days = "".join([str(i) for i in range(1, 8) if f"wd{i}" in data.keys()])
        weeks = ("even" in data.keys(), "odd" in data.keys())
        hour = int(data["prog_time"][:2])
        minute = int(data["prog_time"][3:5])
        t_min = int(data["prog_cmin"])
        t_max = int(data["prog_cmax"])

        instance.edit_or_add_program(chn, prg_num, days, weeks, hour, minute, t_min, t_max)
        return redirect("channel", mqtt_user, chn)

    return render(request, "main/setup_wdays.html",
                  {
                      "mqtt_user": mqtt_user,
                      "chn": chn,
                      "prg_num": prg_num,
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

@login_required
def pump(request, mqtt_user):
    if not ControllerV2Manager.check_auth(mqtt_user=mqtt_user, user=request.user):
        return redirect("/")
    if ControllerV2Manager.check_block(mqtt_user):
        return redirect("controller", mqtt_user)

    instance: ControllerV2Manager = ControllerV2Manager.get_instance(mqtt_user)
    if instance is None:
        raise ValueError(f"Сущность менеджера контроллера '{mqtt_user}' не найдена.")

    if request.method == "POST":
        data = request.POST.dict()
        if all([k in data.keys() for k in ("pmin", "pmax", "vmin", "vmax")]):
            try:
                instance.configure_pump(float(data["pmin"]) * 10, float(data["pmax"]) * 10, float(data["vmin"]), float(data["vmax"]))
            except ValueError:
                pass
        return redirect("controller", mqtt_user)

    pmin, pmax, vmin, vmax = instance.get_pump_settings()

    return render(request, "main/pump.html",
                  {
                      "mqtt_user": mqtt_user,
                      "pmin": "{0:.1f}".format(pmin / 10).replace(",", "."),
                      "pmax": "{0:.1f}".format(pmax / 10).replace(",", "."),
                      "vmin": str(vmin).replace(",", "."),
                      "vmax": str(vmax).replace(",", ".")
                  })

@login_required
def channel(request, mqtt_user, chn, create_prg=False):
    if not ControllerV2Manager.check_auth(mqtt_user=mqtt_user, user=request.user):
        return redirect("/")
    if ControllerV2Manager.check_block(mqtt_user):
        return redirect("controller", mqtt_user)
    def get_day(start, l):
        out = []
        for i in range(24):
            if start <= i < (start + l):
                out.append(1)
            else:
                out.append(0)
        return out

    def get_h_len(t_max):
        l = t_max // 60
        if t_max % 60 > 0:
            l += 1
        return l

    def get_week(chn):
        prgs = Program.objects.filter(channel=chn)
        out = []
        for i in range(7):
            out.append([])
            for j in range(24):
                out[i].append(0)
        for p in prgs:
            days = list(p.days)
            for d in days:
                for i, h in enumerate(get_day(p.hour, get_h_len(p.t_max))):
                    if out[int(d) - 1][i] == 0:
                        out[int(d) - 1][i] += h

        return out

    def norm_time(h, m):
        nh = '0' * (2 - len(str(h))) + str(h)
        nm = '0' * (2 - len(str(m))) + str(m)
        out = f'{nh}:{nm}'
        return out

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

    instance: ControllerV2Manager = ControllerV2Manager.get_instance(mqtt_user)

    if create_prg:
        instance.create_program(chn)
        return redirect("channel", mqtt_user, chn)

    chan: Channel = Channel.objects.get(controller__mqtt_user=mqtt_user, number=chn)
    programs = Program.objects.filter(channel=chan)

    cont = Controller.objects.get(mqtt_user=mqtt_user)
    lines = []
    prgs = []
    lines.append(get_week(chan))
    for pr in programs:
        prgs.append(PrgData(pr.id, pr.days, pr.hour, pr.minute, *pr.get_weeks(), pr.t_min, pr.t_max))
    if instance is not None:
        if request.method == 'POST':
            data = request.POST.dict()
            chan.season = int(data["seasonpc"])
            chan.temp_min = int(data["cmindeg"]) if data["cmindeg"] else chan.temp_min
            chan.temp_max = int(data["cmaxdeg"]) if data["cmaxdeg"] else chan.temp_max
            chan.meandr_on = int(data["meandr_on"]) if data["meandr_on"] else chan.meandr_on
            chan.meaoff_cmin = int(data["meaoff_cmin"]) if data["meaoff_cmin"] else chan.meaoff_cmin
            chan.meaoff_cmax = int(data["meaoff_cmax"]) if data["meaoff_cmax"] else chan.meaoff_cmax
            chan.press_on = float(data["press_on"]) * 10
            chan.press_off = float(data["press_off"]) * 10
            chan.lowlevel = "lowlevel" in data.keys()
            chan.rainsens = "rainsens_on" in data.keys()
            chan.tempsens = int(data["tempsens"])
            instance.command_send_channel(chan.number)
            chan.save()
            return redirect("controller", mqtt_user)

    return render(request, 'main/channel.html',
                  {
                      'mqtt_user': mqtt_user,
                      'chn': int(chn),
                      'prgs': prgs,
                      'prg_data_json': json.dumps([i.toDict() for i in prgs]),
                      'cont': cont,
                      'chan': chan,
                   })

