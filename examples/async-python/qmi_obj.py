import sys
import asyncio
import contextlib
import gi
gi.require_version('Qmi', '1.0')
from gi.repository import GLib, Gio, Qmi, GObject

TIMEOUT=2
STORAGE_TYPE = Qmi.WmsStorageType.NV
MESSAGE_MODE = Qmi.WmsMessageMode.GSM_WCDMA


def _awaitable(f, *args, cancellable=None, user_data=None):
    """Convert a function with a callback to something await-able."""
    loop = asyncio.get_running_loop()
    fut = loop.create_future()

    def callback(*a):
        async def f():
            fut.set_result(a)
        asyncio.run_coroutine_threadsafe(f(), loop)

    args = args + (cancellable, callback, user_data)
    f(*args)
    return fut


class QmiObj(object):
    """A wrapper around a qmi device for more idiomatic method calls."""
    def __init__(self, qmi_obj):
        self._qmi_obj = qmi_obj

    @classmethod
    async def _new_device(cls, path):
        """Factory method to create a qmidevice wrapped in a QmiObject."""
        _self, r, _user_data = await _awaitable(
                Qmi.Device.new, Gio.File.new_for_path(path))
        qmidev = Qmi.Device.new_finish(r)

        obj = cls(qmidev)
        await obj._call('open', Qmi.DeviceOpenFlags.PROXY)
                #Qmi.DeviceOpenFlags.NONE)

        return obj

    async def _call(self, method, *args, timeout=TIMEOUT,
            cancellable=None, user_data=None):
        """The glib dance: call the func, then get the result from _finish."""
        # first returned arg is 'self', basically
        qmidev, generic_result, user_data = await _awaitable(
                getattr(self._qmi_obj, method), *(args + (timeout,)),
                cancellable=cancellable,
                user_data=user_data)
        try:
            actual_result = getattr(
                    self._qmi_obj, f'{method}_finish')(generic_result)
        except GLib.GError as error:
            print(f'Error calling {method}_finish: {error.message}',
                    file=sys.stderr)
            raise
        return actual_result

    def __getattr__(self, name):
        """Allows calling glib methods like you would an async python method."""
        return lambda *a, **kw: self._call(name, *a, **kw)

    def listen(self, indication):
        """Returns an async generator of signal results."""
        #print(GObject.signal_list_names(self._qmi_obj))
        # 'event-report', 'smsc-address'
        loop = asyncio.get_running_loop()
        q = asyncio.Queue()

        def callback(_client, result, **kw):
            """From the glib callback, notify the results_gen of the result."""
            async def f():
                q.put_nowait(result)
            asyncio.run_coroutine_threadsafe(f(), loop)

        async def results_gen():
            """An async generator of results."""
            while True:
                yield await q.get()

        # Connect the callback to the signal
        self._qmi_obj.connect(indication, callback)

        return results_gen()

    @classmethod
    @contextlib.asynccontextmanager
    async def open_device(cls, path):
        """Open a qmi device, properly cleaning it up after and on exceptions."""
        qmidev = await QmiObj._new_device(path)
        
        try:
            yield qmidev
        finally:
            qmidev, result, user_data = await _awaitable(
                    qmidev._qmi_obj.close_async, TIMEOUT)
            qmidev.close_finish(result)


    @contextlib.asynccontextmanager
    async def open_client(self, service, cid=Qmi.CID_NONE):
        """Allocate a qmi client, properly cleaning it up after and on exceptions."""
        # Some specialized clients
        if service == Qmi.Service.WMS:
            qmiclient = SmsClient(await self.allocate_client(service, cid))
        else:
            qmiclient = QmiObj(await self.allocate_client(service, cid))

        try:
            yield qmiclient
        finally:
            await self.release_client(
                    qmiclient._qmi_obj, Qmi.DeviceReleaseClientFlags.RELEASE_CID)


class SmsClient(QmiObj):
    async def get_message(self, index, type_=STORAGE_TYPE):
        """Get the data for the message at the given index."""
        param = Qmi.MessageWmsRawReadInput()
        param.set_message_mode(MESSAGE_MODE)
        param.set_message_memory_storage_id(type_, index)
        message = await self.raw_read(param)
        message.get_result()
        tag, format_, data = message.get_raw_message_data()
        return data

    async def messages(self,
            type_=STORAGE_TYPE, mode=MESSAGE_MODE,
            tag=Qmi.WmsMessageTagType.MT_NOT_READ):
        """Returns a list of the message metadata on the modem."""

        param = Qmi.MessageWmsListMessagesInput()
        param.set_message_mode(mode)
        param.set_message_tag(tag)
        param.set_storage_type(type_)

        messages = await self.list_messages(param)
        messages.get_result()
        lst = messages.get_message_list()
        # If we access the fields after this method returns, the memory has
        # already been freed. So just return the indices.
        return [msg.memory_index for msg in lst]

    async def delete_message(self, index, type_=STORAGE_TYPE):
        param = Qmi.MessageWmsDeleteInput()
        param.set_message_mode(MESSAGE_MODE)
        param.set_memory_index(index)
        param.set_memory_storage(type_)
        message = await self.delete(param)
        message.get_result()

    async def drain_messages(self):
        """Returns a generator of message data that deletes from the modem as it
        retrieves."""
        async for msg_id in self.messages():
            data = await self.get_message(msg_id)
            yield data
            self.delete_message(msg_id)
