"""Windows audio-thread context and serialized PortAudio initialization."""

import sys
import threading

import pyaudio

_thread_context = threading.local()
_interface_lock = threading.RLock()


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
