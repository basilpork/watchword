import json

from concurrent.futures import ThreadPoolExecutor
from django.contrib.auth.decorators import login_required
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.http import HttpResponse, HttpResponseBadRequest
from django.utils import timezone

from ww.api.models import Watch, Ping

executor = ThreadPoolExecutor(max_workers=2)

def ping(r, watchword):
    try:
        watch = Watch.objects.get(word=watchword)
    except Watch.DoesNotExist:
        return HttpResponseBadRequest()

    watch.last_ping = timezone.now()
    # We send flares on state changes
    launch_flares = watch.state == 'alarm'
    watch.state = 'quiet'
    watch.save()

    if launch_flares:
        executor.submit(watch.fire_flares)

    ping = Ping(watch=watch)
    ping.method = r.META["REQUEST_METHOD"]
    ping.user_agent = r.META.get("HTTP_USER_AGENT", "")[:255]
    # There might be several IP addresses stacked up in the headers. We're
    # only going to want the first one.
    addrs = lambda: r.META.get("HTTP_X_FORWARDED_FOR", r.META["REMOTE_ADDR"])
    ping.remote_addr = addrs().split(",")[0]
    ping.save()

    response = HttpResponse("OK")
    # Support CORS, just in case the ping is from JS in a client's browser
    response["Access-Control-Allow-Origin"] = "*"
    return response


def status(r, watchword):
    try:
        watch = Watch.objects.get(word=watchword)
    except Watch.DoesNotExist:
        return HttpResponseBadRequest()

    data = {
        "status": watch.status(),
        "last_ping": None,
        "last_ping_human": "never",
        "seconds_until_alarm": None,
    }

    if watch.last_ping:
        data["last_ping"] = watch.last_ping.isoformat()
        data["last_ping_human"] = naturaltime(watch.last_ping)
        remaining = watch.alarm_threshold() - timezone.now()
        data["seconds_until_alarm"] = int(remaining.total_seconds())

    response = HttpResponse(json.dumps(data))
    response["Content-Type"] = "application/json"
    return response

@login_required
def watches_list(r):
    columns = [
        'Name',
        'Last Ping',
        'Cycle',
        'Grace',
        'Will Alarm',
        'Word',
        'Status',
    ]
    records = []
    for watch in Watch.objects.filter(user=r.user):
        records.append([
            watch.name,
            watch.last_ping.isoformat(),
            # A hack to get human-friendly names for timedelta objects. Simply
            # subtract the timedelta from now in order to let naturaltime
            # create the words from a datetime object, then chop off the " ago"
            # suffix at the end of the string to get the interesting portion.
            naturaltime(timezone.now() - watch.cycle)[:-4],
            naturaltime(timezone.now() - watch.grace)[:-4],
            naturaltime(watch.alarm_threshold()),
            watch.word,
            watch.status(),
        ])
    data = {
        'columns': columns,
        'records': records,
    }
    response = HttpResponse(json.dumps(data))
    response['Content-Type'] = 'application/json'
    return response

