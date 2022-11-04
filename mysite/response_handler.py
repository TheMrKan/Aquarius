import abc
from abc import ABC, abstractmethod
from typing import List
import traceback


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
        except:
            traceback.print_exc()
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
            return c and not data.startswith("*") and len(cls.get_content(data)) == 34
        except:
            traceback.print_exc()
            return False


patterns = [DownloadingDataPattern, PropertiesDataPattern]


def get_matching_pattern(response: str) -> type:
    for p in patterns:
        if issubclass(p, DataPattern):
            if p.match(response):
                return p
    raise PatternNotFoundError(f"Failed to found matching pattern for '{response}'")


def handle_data(obj, data: str) -> bool:
    try:
        pattern: DataPattern = get_matching_pattern(data)
    except PatternNotFoundError:
        return False

    pattern.handle(obj, pattern.get_content(data))
    return True


class Test:

    def handler(self, data):
        print("Handler: ", data)


if __name__ == "__main__":
    t = Test()
    DownloadingDataPattern.handle = type(t).handler
    res = handle_data(t, "*.1.2.3.4.3.2.1.26.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.255.10.11.12.13.12.11.10.")
    print(res)

