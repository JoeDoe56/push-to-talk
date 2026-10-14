"""Windows audio-thread context and serialized PortAudio initialization."""

import sys
import threading
import weakref

import pyaudio

_thread_context = threading.local()
_interface_lock = threading.RLock()
_idle_recorders = weakref.WeakSet()


def register_audio_recorder(recorder):
    with _interface_lock:
        _idle_recorders.add(recorder)


def audio_device_access():
    return _interface_lock


def reopen_audio_interface():
    """Refresh PortAudio's cached endpoints without interrupting a recording.

    The feedback stream must already be closed. Every idle capture interface
    must also be released, otherwise PortAudio retains its old global device
    list even when a new PyAudio object is constructed.
    """
    with _interface_lock:
        for recorder in list(_idle_recorders):
            if not recorder.release_idle_interface():
                return None
        return create_audio_interface()


def default_audio_endpoints():
    """Read live Windows multimedia endpoint IDs, independently of PortAudio."""
    if sys.platform != "win32":
        return None
    import ctypes as ct
    from uuid import UUID

    initialize_audio_thread()
    ole32 = ct.WinDLL("ole32")
    ole32.CoCreateInstance.argtypes = [
        ct.c_void_p,
        ct.c_void_p,
        ct.c_uint,
        ct.c_void_p,
        ct.POINTER(ct.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ct.c_long
    ole32.CoTaskMemFree.argtypes = [ct.c_void_p]
    ole32.CoTaskMemFree.restype = None

    def guid(value):
        return (ct.c_ubyte * 16).from_buffer_copy(UUID(value).bytes_le)

    def method(pointer, slot, *args):
        table = ct.cast(pointer, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
        return ct.WINFUNCTYPE(ct.c_long, ct.c_void_p, *args)(table[slot])

    enumerator = ct.c_void_p()
    result = ole32.CoCreateInstance(
        guid("BCDE0395-E52F-467C-8E3D-C4579291692E"),
        None,
        1,
        guid("A95664D2-9614-4F35-A746-DE8DB63617E6"),
        ct.byref(enumerator),
    )
    if result < 0:
        raise OSError(
            f"Could not enumerate Windows audio devices: 0x{result & 0xFFFFFFFF:08X}"
        )
    endpoints = []
    try:
        for flow in (0, 1):
            device = ct.c_void_p()
            # IMMDeviceEnumerator::GetDefaultAudioEndpoint, eMultimedia.
            result = method(enumerator, 4, ct.c_int, ct.c_int, ct.POINTER(ct.c_void_p))(
                enumerator, flow, 1, ct.byref(device)
            )
            if result < 0:
                endpoints.append(None)
                continue
            identifier = ct.c_void_p()
            try:
                result = method(device, 5, ct.POINTER(ct.c_void_p))(
                    device, ct.byref(identifier)
                )
                if result < 0:
                    raise OSError(
                        f"Could not read Windows audio endpoint: 0x{result & 0xFFFFFFFF:08X}"
                    )
                endpoints.append(ct.wstring_at(identifier))
            finally:
                if identifier:
                    ole32.CoTaskMemFree(identifier)
                method(device, 2)(device)
    finally:
        method(enumerator, 2)(enumerator)
    return tuple(endpoints)


def initialize_audio_thread():
    if sys.platform != "win32" or getattr(_thread_context, "ready", False):
        return
    import ctypes

    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole32.CoInitializeEx.restype = ctypes.c_long
    result = ole32.CoInitializeEx(None, 0)  # Shared multi-threaded COM apartment.
    if result < 0 and result & 0xFFFFFFFF != 0x80010106:
        raise OSError(
            f"Windows audio COM initialization failed: 0x{result & 0xFFFFFFFF:08X}"
        )
    _thread_context.ready = True
    _thread_context.owns_com = result >= 0


def release_audio_thread():
    if sys.platform == "win32" and getattr(_thread_context, "owns_com", False):
        import ctypes

        ctypes.WinDLL("ole32").CoUninitialize()
    _thread_context.ready = False
    _thread_context.owns_com = False


def create_audio_interface():
    initialize_audio_thread()
    with _interface_lock:
        return pyaudio.PyAudio()


def terminate_audio_interface(interface):
    initialize_audio_thread()
    with _interface_lock:
        interface.terminate()
