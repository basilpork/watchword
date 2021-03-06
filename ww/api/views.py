import json

from concurrent.futures import ThreadPoolExecutor
from django.contrib.auth.decorators import login_required
from django.contrib.humanize.templatetags.humanize import naturaltime
from django.http import HttpResponse, HttpResponseBadRequest
from django.utils import timezone

from ww.api.models import Watch, Ping, Flare, Launch

executor = ThreadPoolExecutor(max_workers=2)

def ping(r, watchword):
    try:
        watch = Watch.objects.get(word=watchword)
    except Watch.DoesNotExist:
        return HttpResponseBadRequest()

    # Shortcut if the watch is sleeping (we won't do anything)
    if watch.state == 'sleep':
        response = HttpResponse("Sleeping")
        response["Access-Control-Allow-Origin"] = "*"
        return response

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
    for watch in Watch.objects.filter(user=r.user).order_by('created'):
        records.append([
            watch.name,
            watch.last_ping.isoformat() if watch.last_ping else 'never',
            # A hack to get human-friendly names for timedelta objects. Simply
            # subtract the timedelta from now in order to let naturaltime
            # create the words from a datetime object, then chop off the " ago"
            # suffix at the end of the string to get the interesting portion.
            naturaltime(timezone.now() - watch.cycle)[:-4],
            naturaltime(timezone.now() - watch.grace)[:-4],
            naturaltime(watch.alarm_threshold()) if watch.last_ping else 'never',
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


@login_required
def pings_list(r):
    columns = [
        'Received',
        'Watch',
        'Method',
        'User Agent',
        'Remote IP',
    ]
    records = []
    for ping in Ping.objects.filter(watch__user=r.user).select_related('watch').order_by('-created'):
        records.append([
            ping.created.isoformat(),
            ping.watch.name,
            ping.method,
            ping.user_agent,
            ping.remote_addr,
        ])
    data = {
        'columns': columns,
        'records': records,
    }
    response = HttpResponse(json.dumps(data))
    response['Content-Type'] = 'application/json'
    return response


@login_required
def flares_list(r):
    columns = [
        'Mechanism',
        'Config',
        'Last Launched',
        '# Watches',
    ]
    records = []
    for flare in Flare.objects.filter(user=r.user).order_by('created'):
        try:
            last_launch = Launch.objects.filter(flare=flare).latest('created')
            last_launch = naturaltime(last_launch.created)
        except Launch.DoesNotExist:
            last_launch = 'never'
        records.append([
            flare.signal,
            flare.config,
            last_launch,
            flare.watch_set.count(),
        ])
    data = {
        'columns': columns,
        'records': records,
    }
    response = HttpResponse(json.dumps(data))
    response['Content-Type'] = 'application/json'
    return response


@login_required
def launches_list(r):
    columns = [
        'Launched',
        'Flare',
        'Watch',
        'Trigger State',
    ]
    records = []
    for launch in Launch.objects.filter(watch__user=r.user).order_by('-created'):
        records.append([
            launch.created.isoformat(),
            launch.flare.__str__(),
            launch.watch.name,
            launch.trigger_state,
        ])
    data = {
        'columns': columns,
        'records': records,
    }
    response = HttpResponse(json.dumps(data))
    response['Content-Type'] = 'application/json'
    return response

