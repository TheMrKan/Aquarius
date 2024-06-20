import abc
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Callable
import traceback

logger = logging.getLogger(__name__)

class PatternNotFoundError(Exception):
    pass


class DataPattern(ABC):

    @classmethod
    def match(cls, data: str) -> bool:
        pass

    @staticmethod
    def handle(o, data):
        pass

    @classmethod
    def get_content(cls, data: str) -> List[int]:
        data = data.split("1.2.3.4.3.2.1.")[1]
        data = data.split(".9.8.7.6.7.8.9")[0]
        return list(map(int, data.split(".")))


class DownloadingDataPattern(DataPattern):

    @classmethod
    def match(cls, data: str) -> bool:
        try:
            c = "1.2.3.4.3.2.1." in data and ".10.11.12.13.12.11.10" in data
            return c and data.startswith("*") and len(cls.get_content(data)) == 36
        except Exception as ex:
            logger.error("An error occured in DownloadingDataPattern.match",  exc_info=ex)
            return False

    @classmethod
    def get_content(cls, data: str) -> List[int]:
        data = data.split("1.2.3.4.3.2.1.")[1]
        data = data.split(".10.11.12.13.12.11.10")[0]
        return list(map(int, data.split(".")))


class PropertiesDataPattern(DataPattern):

    @classmethod
    def match(cls, data: str) -> bool:
        try:
            c = "1.2.3.4.3.2.1." in data and ".9.8.7.6.7.8.9" in data
            ln = len(cls.get_content(data))
            return c and not data.startswith("*") and (ln == 34 or ln == 36)
        except Exception as ex:
            logger.error("An error occured in PropertiesDataPattern.match", exc_info=ex)
            return False


patterns = [PropertiesDataPattern, DownloadingDataPattern]


def get_matching_pattern(response: str, overwritings: Dict[type, Callable]) -> type:
    for p in patterns:
        if issubclass(p, DataPattern):
            if p in overwritings.keys():
                default = p.handle
                p.handle = overwritings[p]
                if p.match(response):
                    return p
                p.handle = default
            elif p.match(response):
                return p

    raise PatternNotFoundError(f"Failed to found matching pattern for '{response}'")


def handle_data(obj, data: str, overwritings: Dict[type, Callable] = None) -> bool:
    try:
        pattern: DataPattern = get_matching_pattern(data, overwritings if overwritings is not None else {})
    except PatternNotFoundError:
        return False

    pattern.handle(obj, pattern.get_content(data))
    return True


class Test:

    def handler(self, data):
        print("Handler: ", data)


if __name__ == "__main__":
    t = Test()
    PropertiesDataPattern.handle = type(t).handler
    res = handle_data(t, ".1.2.3.4.3.2.1.23.18.46.5.25.156.0.0.0.0.0.1.0.1.0.0.25.61.0.226.192.168.31.182.1.9.11.13.157.0.0.5.76.127.21.50.9.8.7.6.7.8.9..")
    print(res)

