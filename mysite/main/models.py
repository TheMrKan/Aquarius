from django.db import models
import datetime
from django.contrib.auth.models import User


class UserExtension(models.Model):

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    saved_controllers = models.CharField(max_length=100, default="[]")


class Controller(models.Model):
    status = models.IntegerField(default=2)
    mqtt_host = models.CharField(max_length=30, default="")
    mqtt_port = models.CharField(max_length=30, default="")
    mqtt_user = models.CharField(max_length=30, default="")
    mqtt_password = models.CharField(max_length=30, default="")
    mqtt_prefix = models.CharField(max_length=30, default="")
    email = models.CharField(max_length=50, default="")
    time = models.TimeField(default=datetime.time(0, 0, 0), auto_now=False, auto_now_add=False)
    day = models.IntegerField(default=0)
    week = models.BooleanField(default=False)
    nearest_chn = models.IntegerField(default=1)
    nearest_time = models.TimeField(default=datetime.time(0, 0, 0), auto_now=False, auto_now_add=False)
    t1 = models.FloatField(default=0)
    t1_active = models.BooleanField(default=False)
    t2 = models.FloatField(default=0)
    t2_active = models.BooleanField(default=False)
    t_amount = models.IntegerField(default=1)
    rain = models.BooleanField(default=False)
    pause = models.BooleanField(default=False)
    version = models.IntegerField(default=0)
    ip = models.CharField(max_length=16, default="0.0.0.0")
    esp_v = models.CharField(max_length=12, default="0.0.0")
    esp_connected = models.BooleanField(default=False)
    esp_ap = models.BooleanField(default=False)
    esp_net = models.BooleanField(default=False)
    esp_mqtt = models.BooleanField(default=False)
    esp_errors = models.BooleanField(default=False)
    pressure = models.FloatField(default=0)
    stream = models.FloatField(default=0)
    name = models.CharField(max_length=64, default="Controller")


    def __str__(self):
        return self.name


class Channel(models.Model):
    id = models.AutoField(primary_key=True)
    number = models.IntegerField(default=1)
    name = models.CharField(max_length=64, default="Канал")
    controller = models.ForeignKey('Controller', on_delete=models.CASCADE)
    state = models.BooleanField(default=False)
    season = models.IntegerField(default=100)
    temp_min = models.IntegerField(default=8)
    temp_max = models.IntegerField(default=32)
    meandr_on = models.IntegerField(default=60)
    meaoff_cmin = models.IntegerField(default=0)
    meaoff_cmax = models.IntegerField(default=0)
    press_on = models.FloatField(default=2.1)
    press_off = models.FloatField(default=3.8)
    volume_min = models.FloatField(default=0.0)
    volume_max = models.FloatField(default=0.0)
    lowlevel = models.BooleanField(default=False)
    rainsens = models.BooleanField(default=True)
    tempsens = models.IntegerField(default=1)

    def __str__(self):
        return f"{self.controller.name} / {self.name}"


class Program(models.Model):
    id = models.AutoField(primary_key=True)
    channel = models.ForeignKey('Channel', on_delete=models.CASCADE)
    days = models.CharField(max_length=7, default='')
    weeks = models.SmallIntegerField(default=0)
    hour = models.IntegerField(default=0)
    minute = models.IntegerField(default=0)
    t_min = models.IntegerField(default=0)
    t_max = models.IntegerField(default=0)


    class Meta:
        constraints = []

    def get_weeks(self) -> list:
        bin_weeks = bin(self.weeks)
        output = [bool(int(i)) for i in list(bin_weeks[2:4])]
        if len(output) < 2:
            output += [False, ] * (2 - len(output))
        return output

    def __str__(self):
        return f"{self.channel.controller.name} / {self.channel.number} / ({self.days}|{self.hour}:{self.minute})"


