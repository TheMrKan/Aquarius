import main.conf as conf


def site_name(request):
    return {"site_name": conf.SITE_NAME}


def protocols(request):
    return {"use_ssl": conf.USE_SSL, "http":  "https" if conf.USE_SSL else "http", "ws": "wss" if conf.USE_SSL else "ws"}
