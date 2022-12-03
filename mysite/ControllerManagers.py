import time

from MQTTManager import MQTTManager
from main.models import Controller, Channel, UserExtension, Program
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
import datetime
from bitstring import BitArray
from django.contrib.auth.models import User
import json
from typing import List, Tuple
from main.consumers import ControllerConsumer
import threading
import response_handler
import traceback


def try_int(i):
    try:
        return int(i)
    except:
        return 0


class LimitOfProgramsException(Exception):
    pass


class ControllerV2Manager:

    DEFAULT_HOST = "hd.tlt.ru"
    DEFAULT_PORT = "18883"
    DEFAULT_PREFIX_PATTERN = "{user}/"
    DEFAULT_NAME_PATTERN = "Контроллер {user}"

    instances = {}

    cmd_pattern = ".1.2.3.4.3.2.1.{request_code}.{payload}.{check_sum[0]}.{check_sum[1]}.9.8.7.6.7.8.9.9."
    topic_send = "aqua_smart"
    topic_receive = "aqua_kontr"
    topic_status = "tele/Aquarius/LWT"
    topic_send_status = "smart_LWT"

    pump_channel_number = 10
    max_programs_for_channel = 14

    user: str
    command_response_handlers: dict

    blocked: bool = False
    packet: int = -1
    stashed_data: list = []
    last_command: str
    data_model: Controller
    mqtt_manager: MQTTManager

    @staticmethod
    def check_block(user: str):
        c = ControllerV2Manager.get_instance(user, False)
        if c is None:
            return True
        return c.blocked

    @staticmethod
    def get_instance(user: str, create: bool = True):
        _filtered_controllers = Controller.objects.filter(mqtt_user=user)

        if user in ControllerV2Manager.instances.keys():
            return ControllerV2Manager.instances[user]
        elif _filtered_controllers.exists() and create:
            data_model = _filtered_controllers[0]
            if ControllerV2Manager.check_auth(data_model.mqtt_user, data_model.mqtt_password):
                print("Auth: OK")
                if ControllerV2Manager.add(data_model.mqtt_user, data_model.mqtt_password):
                    return ControllerV2Manager.instances[user]
                else:
                    return None
            else:
                return None
        else:
            return None

    @staticmethod
    def add(user: str, password: str, **kwargs):
        if ControllerV2Manager.get_instance(user, False) is None:
            print("get instance is none")
            mqtt = MQTTManager.try_connect(kwargs.get("host", ControllerV2Manager.DEFAULT_HOST),
                                           kwargs.get("port", ControllerV2Manager.DEFAULT_PORT),
                                           user,
                                           password,
                                           kwargs.get("prefix", ControllerV2Manager.DEFAULT_PREFIX_PATTERN.format(user=user)))
            if mqtt is not None:
                cm = ControllerV2Manager(kwargs.get("host", ControllerV2Manager.DEFAULT_HOST),
                                         kwargs.get("port", ControllerV2Manager.DEFAULT_PORT),
                                         user,
                                         password,
                                         kwargs.get("prefix", ControllerV2Manager.DEFAULT_PREFIX_PATTERN.format(user=user)),
                                         mqtt)
                if "email" in kwargs.keys():
                    cm.set_email(kwargs["email"])
                if "cname" in kwargs.keys():
                    cm.set_name(kwargs["cname"])
                cm.subscribe(mqtt)
                cm.on_connected(mqtt)
                return True
            else:
                return False
        else:
            return True

    @staticmethod
    def check_auth(mqtt_user: str = "", password: str = "") -> bool:
        try:
            data_model = Controller.objects.get(mqtt_user=mqtt_user, mqtt_password=password)
        except ObjectDoesNotExist:
            return False
        return data_model is not None and data_model.mqtt_user == mqtt_user and data_model.mqtt_password == password

    def __init__(self, host: str, port: int,  controller_user: str, password: str, prefix: str, mqtt_manager: MQTTManager):
        ControllerV2Manager.instances[controller_user] = self

        try:
            self.data_model = Controller.objects.get(mqtt_user=controller_user)
        except ObjectDoesNotExist:
            print("Create")
            self.data_model = Controller(mqtt_user=controller_user,
                                         mqtt_password=password,
                                         mqtt_host=host,
                                         mqtt_port=port,
                                         mqtt_prefix=prefix,
                                         )
            self.data_model.save()

        # при инициализации устанавливаем значение 2 (контроллер ни разу не подключался к брокеру)
        # если при подключении менеджера будет получен топик LWT, то перезаписываем состояние на то, что указано в топике
        # если не будет получен, значит топика нет, а следовательно контроллер ни разу не подключался к брокеру
        self.data_model.status = 2
        self.data_model.save()

        self.is_user_connected = False

        for channel_num in range(1, 31):
            try:
                channel = Channel.objects.get(controller=self.data_model, number=channel_num)
            except ObjectDoesNotExist:
                channel = Channel(controller=self.data_model, name=f"Канал {channel_num}", number=channel_num, )
                channel.save()
            except MultipleObjectsReturned:
                Channel.objects.filter(controller=self.data_model, number=channel_num).delete()

        self.mqtt_manager = mqtt_manager
        self.user = controller_user
        self.wrong_packets = 0
        self.previous_time = datetime.time(0, 0, 0)
        self.command_response_handlers = {
            "8.8.8.8.8.8.8.8": self.command_get_state_response,
            "0.0.8": self.command_get_channels_response,
        }

    def unload(self) -> None:
        self.send_status(False)
        self.mqtt_manager.unsubscribe(self.topic_receive)
        self.mqtt_manager.unsubscribe(self.topic_status)
        del self

    def subscribe(self, mqtt: MQTTManager) -> None:
        mqtt.subscribe(self.topic_receive, self.handle_message)
        mqtt.subscribe(self.topic_status, self.handle_status_message)
        mqtt.onConnected = self.on_connected

    def send_command(self, request_code: str, payload: str = ""):
        if not self.blocked:
            msg = self.wrap_command(request_code, payload)
            self.last_command = request_code
            self.mqtt_manager.send(self.topic_send, msg)

    def turn_off_all_channels(self):
        active_channels = Channel.objects.filter(controller__mqtt_user=self.user, state=True)

        for i in active_channels:
            self.command_turn_on_channel(i.number, 0)

    def send_status(self, status: bool):
        print("Send status:", status)
        self.is_user_connected = status
        self.mqtt_manager.send(self.topic_send_status, str(int(status)), retain=True)

    def wrap_command(self, request_code: str, payload: str) -> str:
        return self.cmd_pattern.format(request_code=request_code, payload=payload,
                                       check_sum=self.get_check_sum(request_code, payload))

    def get_pump_state(self) -> bool:
        """
        Если давление включения и выключения на канале насоса равны, то возвращает False
        :return:
        Включен или выключен насос
        """
        pump_channel: Channel = Channel.objects.get(controller=self.data_model, number=self.pump_channel_number)
        return pump_channel.press_on != pump_channel.press_off

    def get_pump_settings(self) -> Tuple[float]:
        """
        Возвращает настройки насоса
        :return:
        Давление включения, давление выключения, минимальный расход, максимальный расход
        """
        pump_channel: Channel = Channel.objects.get(controller=self.data_model, number=self.pump_channel_number)
        return pump_channel.press_on, pump_channel.press_off, pump_channel.volume_min, pump_channel.volume_max

    def configure_pump(self, pressure_min: float, pressure_max: float,
                       volume_min: float, volume_max: float) -> None:
        pump_channel: Channel = Channel.objects.get(controller=self.data_model, number=self.pump_channel_number)

        pump_channel.press_on = pressure_min
        pump_channel.press_off = pressure_max
        pump_channel.volume_min = volume_min
        pump_channel.volume_max = volume_max
        pump_channel.save()

        self.command_send_channel(self.pump_channel_number)

    def command_turn_on_channel(self, channel_num, minutes) -> None:
        minutes_bytes = minutes.to_bytes(2, "big")
        self.send_command("0.0.2", f"{channel_num}.{minutes_bytes[0]}.{minutes_bytes[1]}")

    def command_pause(self, minutes) -> None:
        minutes_bytes = minutes.to_bytes(2, "big")
        self.send_command("0.0.7", f"{minutes_bytes[0]}.{minutes_bytes[1]}")

    def command_get_channels(self) -> None:
        self.wrong_packets = 0
        self.packet = -1
        self.send_command("0.0.8")

    def set_email(self, email: str):
        self.data_model.email = email
        self.data_model.save()

    def edit_or_add_program(self, channel_num: int, prg_id: int, days: str, weeks: tuple, start_hour: int, start_minute: int, t_min: int, t_max: int) -> Program:
        chan = Channel.objects.get(controller__mqtt_user=self.data_model.mqtt_user, number=channel_num)
        if prg_id is None:
            prg = Program()
        else:
            prg = Program.objects.filter(id=prg_id)
        if len(prg) > 0:
            prg = prg[0]
        else:
            prg = Program()
        prg.channel = chan
        prg.number = prg_id
        prg.days = days
        prg.weeks = int(f'{int(weeks[0])}{int(weeks[1])}', 2)
        prg.hour = start_hour
        prg.minute = start_minute
        prg.t_min = t_min
        prg.t_max = t_max
        prg.save()
        self.command_send_channel(channel_num)
        return prg

    def create_program(self, channel_num: int) -> Program:
        chan = Channel.objects.get(controller__mqtt_user=self.data_model.mqtt_user, number=channel_num)

        programs_exists = len(Program.objects.filter(channel=chan))
        if programs_exists >= self.max_programs_for_channel:
            raise LimitOfProgramsException

        prg = Program()
        prg.channel = chan
        prg.days = "1234567"
        prg.weeks = 3
        prg.hour = 0
        prg.minute = 0
        prg.t_min = 20
        prg.t_max = 40
        prg.save()
        self.command_send_channel(channel_num)
        return prg

    def remove_program(self, channel_num: int, prg_id: int):
        try:
            program = Program.objects.get(id=prg_id)
        except ObjectDoesNotExist:
            return

        program.delete()

    def command_send_channel(self, chn):
        channel = Channel.objects.get(controller=self.data_model, number=chn)
        chn_settings = [channel.temp_min, channel.temp_max, channel.meandr_on, channel.meaoff_cmin, channel.meaoff_cmax,
                        int(channel.press_on), int(channel.press_off), 0, 0,
                        channel.season, 0, 0, 0, int(channel.rainsens), channel.tempsens, 0, 0, 0, 0, 0]
        programs = Program.objects.filter(channel=channel)
        print(chn_settings)
        prgs = []
        print(channel, programs)
        for prg in programs:
            days = int(''.join([(str(int(str(i) in prg.days))) for i in range(1, 8)]), 2)
            prg_data = [days, prg.weeks, prg.hour, prg.minute, prg.t_min, prg.t_max]
            prgs.append(".".join([str(i) for i in prg_data]))
        str_data = ".".join([str(i) for i in chn_settings]) + "." + ".".join([str(i) for i in prgs])
        self.send_command(f"0.{channel.number}.6", str_data)

    def command_get_channels_response(self, content: List[int]) -> bool:
        bytes_in_packet = 35
        total_packets = 27
        print("Content: ", content)
        try:

            parsed_message = content

            packet_number = parsed_message[0]

            del parsed_message[0]
            print(packet_number, self.packet + 1, len(parsed_message))
            if packet_number != self.packet + 1 or len(parsed_message) != bytes_in_packet:
                if self.wrong_packets >= 5:
                    self.packet = -1
                    self.stashed_data = []
                    self.blocked = False
                    ControllerConsumer.send_data_downloaded(self.data_model.mqtt_user, "ERROR")
                    return True
                else:
                    self.wrong_packets += 1
                    return False

            missed_bytes = max((packet_number - self.packet - 1), 0) * bytes_in_packet
            self.stashed_data += [0] * missed_bytes
            self.stashed_data += parsed_message
            self.packet = packet_number
            print(f"Packet: {packet_number}")
            self.wrong_packets = 0

            if packet_number >= total_packets - 1:
                [print(f"{n}: {i}") for n, i in enumerate(self.stashed_data)]
                if len(self.stashed_data) != total_packets * bytes_in_packet:
                    print("Invalid data")
                    print("Error 2")
                    ControllerConsumer.send_data_downloaded(self.data_model.mqtt_user, "ERROR")
                    self.packet = -1
                    self.stashed_data = []
                    self.blocked = False
                    return True

                total_channels = 10
                bytes_for_channel = 20
                for i in range(total_channels):
                    offset = bytes_for_channel * i + 20
                    try:
                        channel_model: Channel = Channel.objects.get(controller=self.data_model, number=i+1)
                    except ObjectDoesNotExist:
                        channel_model: Channel = Channel(controller=self.data_model, number=i+1, name=f"Канал {i+1}")

                    Program.objects.filter(channel=channel_model).delete()

                    c_properties = self.stashed_data[offset:offset+20]
                    channel_model.temp_min = c_properties[0]
                    channel_model.temp_max = c_properties[1]
                    channel_model.meandr_on = c_properties[2]
                    channel_model.meaoff_cmin = c_properties[3]
                    channel_model.meaoff_cmax = c_properties[4]
                    channel_model.press_on = c_properties[5]
                    channel_model.press_off = c_properties[6]
                    channel_model.season = c_properties[9]
                    channel_model.rainsens = bool(c_properties[13])
                    channel_model.tempsens = c_properties[14]
                    channel_model.lowlevel = bool(c_properties[15])

                    print(self.stashed_data[offset:offset+20])

                    channel_model.save()

                total_programs = 80
                bytes_for_program = 8
                for i in range(total_programs):
                    offset = bytes_for_program * i + 240
                    print(offset)
                    print(f"Processing channel {self.stashed_data[offset]}; program {self.stashed_data[offset+1]}")
                    try:
                        if 255 in self.stashed_data[offset:offset+bytes_for_program]:
                            print("Skip empty program")
                            continue
                        channel_model: Channel = Channel.objects.get(controller=self.data_model, number=self.stashed_data[offset])
                        print("Got channel model:", channel_model)
                        try:
                            program_model: Program = Program.objects.filter(channel=channel_model)[self.stashed_data[offset+1]]
                            print("Program found in DB")
                        except ObjectDoesNotExist:
                            program_model: Program = Program(channel=channel_model)
                            print(f"Program created because ObjectDoesNotExistsError with id {program_model.id}")
                        except IndexError:
                            program_model: Program = Program(channel=channel_model)
                            print(f"Program created because IndexError with id {program_model.id}")

                        program_model.days = ''.join([str(num+1) for num, j in enumerate(list("{0:b}".format(self.stashed_data[offset + 2]))) if bool(int(j))])
                        program_model.weeks, program_model.hour, program_model.minute, program_model.t_min,\
                        program_model.t_max = self.stashed_data[offset+3:offset+8]

                        program_model.save()
                        print(f"Program saved with properties: id = {program_model.id}; days = {program_model.days}; weeks = {program_model.weeks}")
                    except Exception as ex1:
                        traceback.print_exc()
                        continue
                ControllerConsumer.send_data_downloaded(self.data_model.mqtt_user)
                self.packet = -1
                self.stashed_data = []
                self.blocked = False
                self.wrong_packets = 0
                self.command_get_state()
                return True
        except Exception as ex:
            traceback.print_exc()
            self.packet = -1
            self.stashed_data = []
            self.blocked = False
            ControllerConsumer.send_data_downloaded(self.data_model.mqtt_user, "ERROR")
            return True
        return False

    def command_get_30_channels_response(self, content: List[int]) -> bool:
        bytes_in_packet = 35
        total_packets = 75
        print("30 chns content: ", content)

        try:

            parsed_message = content

            packet_number = parsed_message[0]

            del parsed_message[0]
            print(packet_number, self.packet + 1, len(parsed_message))
            if packet_number != self.packet + 1 or len(parsed_message) != bytes_in_packet:
                if self.wrong_packets >= 5:
                    self.packet = -1
                    self.stashed_data = []
                    self.blocked = False
                    ControllerConsumer.send_data_downloaded(self.data_model.mqtt_user, "ERROR")
                    self.wrong_packets = 0
                    return True
                else:
                    self.wrong_packets += 1
                    return False

            if packet_number == 40:
                self.blocked = False
                self.command_get_state()
                self.blocked = True

            missed_bytes = max((packet_number - self.packet - 1), 0) * bytes_in_packet
            self.stashed_data += [0] * missed_bytes
            self.stashed_data += parsed_message
            self.packet = packet_number
            print(f"Packet: {packet_number}")
            self.wrong_packets = 0

            if packet_number >= total_packets - 1:
                [print(f"{n}: {i}") for n, i in enumerate(self.stashed_data)]
                if len(self.stashed_data) != total_packets * bytes_in_packet:
                    print("Invalid data")
                    print("Error 2")
                    ControllerConsumer.send_data_downloaded(self.data_model.mqtt_user, "ERROR")
                    self.packet = -1
                    self.stashed_data = []
                    self.blocked = False
                    self.wrong_packets = 0
                    return True

                total_channels = 30
                bytes_for_channel = 20
                for i in range(total_channels):
                    offset = bytes_for_channel * i + 20
                    try:
                        channel_model: Channel = Channel.objects.get(controller=self.data_model, number=i+1)
                    except ObjectDoesNotExist:
                        channel_model: Channel = Channel(controller=self.data_model, number=i+1, name=f"Канал {i+1}")

                    Program.objects.filter(channel=channel_model).delete()

                    c_properties = self.stashed_data[offset:offset+20]
                    channel_model.temp_min = c_properties[0]
                    channel_model.temp_max = c_properties[1]
                    channel_model.meandr_on = c_properties[2]
                    channel_model.meaoff_cmin = c_properties[3]
                    channel_model.meaoff_cmax = c_properties[4]
                    channel_model.press_on = c_properties[5]
                    channel_model.press_off = c_properties[6]
                    channel_model.season = c_properties[9]
                    channel_model.rainsens = bool(c_properties[13])
                    channel_model.tempsens = c_properties[14]
                    channel_model.lowlevel = bool(c_properties[15])

                    print(self.stashed_data[offset:offset+20])

                    channel_model.save()

                total_programs = 200
                bytes_for_program = 8
                for i in range(total_programs):
                    offset = bytes_for_program * i + 640
                    print(offset)
                    print(f"Processing channel {self.stashed_data[offset]}; program {self.stashed_data[offset+1]}")
                    try:
                        if 255 in self.stashed_data[offset:offset+bytes_for_program] or self.stashed_data[offset] == 0:
                            print("Skip empty program")
                            continue
                        channel_model: Channel = Channel.objects.get(controller=self.data_model, number=self.stashed_data[offset])
                        print("Got channel model:", channel_model)
                        try:
                            program_model: Program = Program.objects.filter(channel=channel_model)[self.stashed_data[offset+1]]
                            print("Program found in DB")
                        except ObjectDoesNotExist:
                            program_model: Program = Program(channel=channel_model)
                            print(f"Program created because ObjectDoesNotExistsError with id {program_model.id}")
                        except IndexError:
                            program_model: Program = Program(channel=channel_model)
                            print(f"Program created because IndexError with id {program_model.id}")

                        program_model.days = ''.join([str(num+1) for num, j in enumerate(list("{0:b}".format(self.stashed_data[offset + 2]))) if bool(int(j))])
                        program_model.weeks, program_model.hour, program_model.minute, program_model.t_min,\
                        program_model.t_max = self.stashed_data[offset+3:offset+8]

                        program_model.save()
                        print(f"Program saved with properties: id = {program_model.id}; days = {program_model.days}; weeks = {program_model.weeks}")
                    except Exception as ex1:
                        traceback.print_exc()
                        continue
                ControllerConsumer.send_data_downloaded(self.data_model.mqtt_user)
                self.packet = -1
                self.stashed_data = []
                self.blocked = False
                self.wrong_packets = 0
                self.command_get_state()
                return True
        except Exception as ex:
            traceback.print_exc()
            self.packet = -1
            self.stashed_data = []
            self.blocked = False
            ControllerConsumer.send_data_downloaded(self.data_model.mqtt_user, "ERROR")
            return True
        return False

    def get_controller_properties(self) -> dict:
        channels = Channel.objects.filter(controller__mqtt_user=self.data_model.mqtt_user)
        channels_state = [i.state for i in channels]

        properties = {
            "status": self.data_model.status,
            "hour": self.data_model.time.hour,
            "minute": self.data_model.time.minute,
            "second": self.data_model.time.second,
            "day_of_week": self.data_model.day,
            "even_week": self.data_model.week,
            "next_chn": self.data_model.nearest_chn,
            "next_time_hour": self.data_model.nearest_time.hour,
            "next_time_minute": self.data_model.nearest_time.minute,
            "temp1": self.data_model.t1,
            "temp1_active": self.data_model.t1_active,
            "temp2": self.data_model.t2,
            "temp2_active": self.data_model.t2_active,
            "temp_amount": self.data_model.t_amount,
            "rain": self.data_model.rain,
            "pause": self.data_model.pause,
            "version": self.data_model.version,
            "ip": self.data_model.ip,
            "esp_v": self.data_model.esp_v,
            "esp_connected": self.data_model.esp_connected,
            "esp_ap": self.data_model.esp_ap,
            "esp_net": self.data_model.esp_net,
            "esp_mqtt": self.data_model.esp_mqtt,
            "esp_errors": self.data_model.esp_errors,
            "pressure": self.data_model.pressure,
            "stream": self.data_model.stream,
            "channels_state": channels_state,
            "pump_state": self.get_pump_state(),
            "channels_meandrs": [i.meaoff_cmin != 0 or i.meaoff_cmax != 0 for i in channels],
        }

        return properties


    def command_get_state(self) -> None:
        self.send_command("8.8.8.8.8.8.8.8")

    def command_set_time(self, year, month, day, hour, minute, second):

        data = '.'.join([str(i) for i in [minute, hour, second, day, month, year % 100]])
        self.send_command("0.0.1", data)

    def command_get_state_response(self, content) -> bool:
        try:

            s = [0, 0, 0, 0, 0, 0, 0, 0] + content
            #[print(f"{num}: {i}") for num, i in enumerate(s)]

            self.data_model.version = s[27]    # сначала получаем версию прошивки, чтобы в зависимости от неё обрабатывать входные данные

            is_time_updated = False
            new_time = datetime.time(s[8], s[9], s[10])
            if new_time != self.previous_time:
                self.previous_time = self.data_model.time
                self.data_model.time = new_time
                is_time_updated = True

            self.data_model.day = s[11]
            self.data_model.week = bool(s[21])
            self.data_model.nearest_chn = s[23]
            try:
                self.data_model.nearest_time = datetime.time(s[24], s[25])
            except ValueError:
                self.data_model.nearest_time = datetime.time(0, 0)

            # прошивки старше 161 версии могут передавать отрицательные температуры
            # преобразование:
            # t, при t < 128
            # t - 256, при t >= 128
            # если приходит -100, значит датчик не активен. Необходимо устанавливать температуру 20, и на странице выводить температуру другим цветом
            # t1_active и t2_active показывают, активны ли датчики
            if self.data_model.version < 161:
                self.data_model.t1 = s[12]
                self.data_model.t2 = s[13]

                # у прошивок младше 161 нет возможности понять, работает ли датчик, поэтому всегда показываем, что активен
                self.data_model.t1_active = True
                self.data_model.t2_active = True

            else:
                self.data_model.t1 = s[12] if s[12] < 128 else s[12] - 256
                self.data_model.t2 = s[13] if s[13] < 128 else s[13] - 256

                # проверяем, активен ли датчик 1
                if self.data_model.t1 == -100:
                    self.data_model.t1 = 20    # если не активен, то необходимо отображать температуру 20
                    self.data_model.t1_active = False
                else:
                    self.data_model.t1_active = True
                # проверяем, активен ли датчик 2
                if self.data_model.t2 == -100:
                    self.data_model.t2 = 20    # если не активен, то необходимо отображать температуру 20
                    self.data_model.t2_active = False
                else:
                    self.data_model.t2_active = True

            self.data_model.t_amount = s[19]
            self.data_model.rain = bool(s[14])
            self.data_model.pause = bool(s[26])

            self.data_model.ip = f"{s[28]}.{s[29]}.{s[30]}.{s[31]}"
            self.data_model.esp_v = f"{s[32]}.{s[33]}.{s[34]}"
            esp_d = BitArray(uint=s[35], length=8)[::-1]
            self.data_model.esp_connected = esp_d[0]
            self.data_model.esp_ap = esp_d[1]
            self.data_model.esp_net = esp_d[2]
            self.data_model.esp_mqtt = esp_d[3]
            self.data_model.esp_errors = esp_d[4]
            self.data_model.pressure = s[36] - 10
            self.data_model.stream = s[37]
            self.data_model.num = f"{s[39]}-{s[40]}"

            db_chns = {i.number: i for i in Channel.objects.filter(controller=self.data_model)}
            chns = list(list(BitArray(uint=s[15], length=8)))[::-1] + list(BitArray(uint=s[16], length=8))[::-1] + list(
                BitArray(uint=s[17], length=8))[::-1] + list(BitArray(uint=s[18], length=8)[::-1])
            for c in db_chns.keys():
                if c < len(chns):
                    s = chns[db_chns[c].number-1]
                    if db_chns[c].state != s:
                        db_chns[c].state = s
                        db_chns[c].save()
            self.data_model.save()

            ControllerConsumer.send_properties(self.user, self.get_controller_properties(),
                                               is_time_updated=is_time_updated)

            return False
        except Exception as ex:
            traceback.print_exc()
            return False

    def get_remote_blocks(self) -> Tuple:
        return self.data_model.remote_block0, self.data_model.remote_block1, self.data_model.remote_block2

    def set_remote_blocks(self, rblock0: int, rblock1: int, rblock2: int):
        rblock0 = rblock0 % 10000
        rblock1 = rblock1 % 10000
        rblock2 = rblock2 % 10000

        self.data_model.remote_block0 = rblock0
        self.data_model.remote_block1 = rblock1
        self.data_model.remote_block2 = rblock2
        self.data_model.save()

        self.send_command("0.1.1", ".".join([".".join([str(i) for i in f"{rb:0>4}"]) for rb in (rblock0, rblock1, rblock2)]))

    def on_connected(self, mqtt: MQTTManager):
        self.command_get_state()

    def get_check_sum(self, *data: str) -> (int, int):
        check_sum = 0
        for d in data:
            for i in d.split("."):
                if i.isdigit():
                    check_sum += int(i)
        check_sum_bytes = check_sum.to_bytes(2, "big")
        return check_sum_bytes[0], check_sum_bytes[1]

    def handle_message(self, mqtt: MQTTManager, controller_prefix: str, data: str) -> None:
        #print(f"{self.is_user_connected=}")
        if self.is_user_connected:

            response_handler.handle_data(self, data, None if self.data_model.version < 200 else
                                         {
                                             response_handler.DownloadingDataPattern: type(self).command_get_30_channels_response
                                         })

    def handle_status_message(self, mqtt: MQTTManager, controller_prefix: str, data: str) -> None:
        print("Handle status data:", data)
        st = try_int(data)
        self.data_model.status = int(bool(st))
        self.data_model.save()


# регистрируем обработчики для паттернов данных
response_handler.DownloadingDataPattern.handle = ControllerV2Manager.command_get_channels_response
response_handler.PropertiesDataPattern.handle = ControllerV2Manager.command_get_state_response

