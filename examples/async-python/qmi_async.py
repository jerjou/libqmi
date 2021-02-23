#!/usr/bin/env python
# -*- Mode: python; tab-width: 4; indent-tabs-mode: nil; c-basic-offset: 4 -*-
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License along
# with this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright (C) 2021 Aleksander Morgado <aleksander@aleksander.es>

import asyncio
import asyncio_glib
asyncio.set_event_loop_policy(asyncio_glib.GLibEventLoopPolicy())

from aiostream.stream import merge
from aiostream.core import streamcontext
import contextlib
from datetime import datetime, timedelta
import leapseconds
import pytz, tzlocal
import sys, signal, gi
from qmi_obj import QmiObj

gi.require_version('Qmi', '1.0')
from gi.repository import GLib, Gio, Qmi, GObject


def _from_gps_epoch(millis):
    """Returns a local datetime represented by the millis given in gps epoch."""
    utc = leapseconds.gps_to_utc(
            datetime(1980,1,6) + timedelta(milliseconds=millis))
    return pytz.utc.localize(utc).astimezone(tzlocal.get_localzone())


async def get_signal_strength(qmidev):
    async with qmidev.open_client(Qmi.Service.NAS) as qmiclient:
        param = Qmi.MessageNasGetSignalStrengthInput()
        strength = await qmiclient.get_signal_strength(param)
        strength.get_result()
        return strength.get_signal_strength()


async def get_time(qmidev):
    """Returns the modem's time as a localized datetime."""
    async with qmidev.open_client(Qmi.Service.DMS) as qmiclient:
        time = await qmiclient.get_time(None)
        time.get_result()
        systime = time.get_system_time()
        return _from_gps_epoch(systime)


async def sms_list(qmidev):
    """Lists all the messages on the modem."""
    async with qmidev.open_client(Qmi.Service.WMS) as qmiclient:
        return [await qmiclient.get_message(msg_id)
                for msg_id in await qmiclient.messages()]


async def sms_get(qmidev, msg_id):
    """Gets the given message."""
    async with qmidev.open_client(Qmi.Service.WMS) as qmiclient:
        return await qmiclient.get_message(msg_id)


async def sms_rm(qmidev, msg_id):
    """Removes the specified message."""
    async with qmidev.open_client(Qmi.Service.WMS) as qmiclient:
        return await qmiclient.delete_message(int(msg_id))


async def sms_received(result):
    """Callback for incoming sms indication."""
    print(result)


async def voice_received(result):
    """Callback for new incoming voice call indications."""
    (success, call_info) = result.get_call_information()
    print(f'Whether the call is incoming, etc: {call_info[0].state}')

    (success, remote_party) = result.get_remote_party_number()
    print(f'Internal call id: {remote_party[0].id}')
    print(f'Call from: {remote_party[0].type}')


@contextlib.asynccontextmanager
async def withs(*contexts, prev_contexts=[]):
    """async-with doesn't seem to work with multiple contexts. Shim for that."""
    async with contexts[0] as c:
        if len(contexts) == 1:
            yield prev_contexts + [c]
        else:
            async with withs(*contexts[1:],
                    prev_contexts=prev_contexts + [c]) as combined:
                yield combined


async def daemon(qmidev):
    """Listens for incoming sms and voice."""
    async with withs(
            qmidev.open_client(Qmi.Service.WMS),
            qmidev.open_client(Qmi.Service.VOICE),
            ) as (wms_client, voice_client):

        # Enable the event-report indication on the WMS service
        param = Qmi.MessageWmsSetEventReportInput()
        param.set_new_mt_message_indicator(True)
        await wms_client.set_event_report(param)

        # Enable voice indications
        param = Qmi.MessageVoiceIndicationRegisterInput()
        param.set_call_notification_events(True)
        await voice_client.indication_register(param)

        # Combine them so that we can handle whichever event happens first
        combined = merge(
                wms_client.listen('event-report'),
                voice_client.listen('all-call-status'),
                )
        print("Listening...")
        async with combined.stream() as streamer:
            async for result in streamer:
                if isinstance(result, Qmi.IndicationWmsEventReportOutput):
                    asyncio.create_task(sms_received(result))
                elif isinstance(result, Qmi.IndicationVoiceAllCallStatusOutput):
                    asyncio.create_task(voice_received(result))
                else:
                    print(result)
                    print(dir(result))


async def main(path, funcname, *args):
    """Opens the qmi device, and delegates to the requested function."""
    # Handle interrupts
    signal_handler = lambda *a: asyncio.get_running_loop().stop()
    for s in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, s, signal_handler, None)

    async with QmiObj.open_device(path) as qmidev:
        if funcname in FUNCS:
            print(await FUNCS[funcname](qmidev, *args))
        else:
            raise Exception(f"Invalid: {funcname}\nNeed one of: {FUNCS.keys()}")


# A dict mapping the name of a function you can request as a command-line
# argument, to the actual python function that does the work.
FUNCS = {
        'signal-strength': get_signal_strength,
        'time': get_time,
        'daemon': daemon,
        'sms-list': sms_list,
        'sms-get': sms_get,
        'sms-rm': sms_rm,
        }


if __name__ == "__main__":
    # Process input arguments
    if len(sys.argv) < 3:
        print('error: wrong number of arguments', file=sys.stderr)
        print(f'usage: {sys.argv[0]} <DEVICE> <{"|".join(FUNCS.keys())}>')
        sys.exit(1)

    try:
        asyncio.run(main(sys.argv[1], sys.argv[2], *sys.argv[3:]))
    except KeyboardInterrupt:
        pass
