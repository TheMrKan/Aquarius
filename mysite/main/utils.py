from typing import Callable
import logging
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
import mysite.user_tools as user_tools
from django.core.handlers.asgi import ASGIRequest
from functools import wraps
from mysite.ControllerManagers import ControllerV2Manager, IncorrectCredentialsException

logger = logging.getLogger(__name__)

def controller_instance_required(func: Callable):
    @wraps(func)
    def wrapper(*args, **kwargs):
        mqtt_user: str | None = kwargs.get("mqtt_user", None)
        if not mqtt_user:
            logger.error(f"Controller auth is required for view func '{func.__name__} but 'mqtt_user' is not provided'")
            return redirect("/")

        try:
            instance = ControllerV2Manager.get_instance(mqtt_user)
        except IncorrectCredentialsException as ex:
            logger.error("controller_instance_required decorator failed because of incorrect credentials", exc_info=ex)
            return redirect("/")

        kwargs["controller_instance"] = instance
        return func(*args, **kwargs)

    return login_required(wrapper)

def ensure_not_blocked(func: Callable):
    @wraps(func)
    def wrapper(*args, controller_instance: ControllerV2Manager, **kwargs):
        if controller_instance.check_block():
            logger.info("Redirecting to the controller's main page because the controler is blocked")
            return redirect("controller", controller_instance.user)
        return func(*args, controller_instance=controller_instance, **kwargs)

    return login_required(controller_instance_required(wrapper))