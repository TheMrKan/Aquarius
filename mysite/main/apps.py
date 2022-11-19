from django.apps import AppConfig
from django.conf import settings
from multiprocessing import Process


class MainConfig(AppConfig):
    name = 'main'
    verbose_name = "Main app"

    manager = None
    counter = 0

    process = None

    def ready(self):
        '''try:
            from main.models import Controller
            from ControllerManagers import ControllerV2Manager
            for c in Controller.objects.all():
                ControllerV2Manager.add(c.prefix, c.password)
        except:
            pass'''

