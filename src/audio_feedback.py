"""Keep the Windows output stream ready for immediate, uninterrupted chimes."""

from array import array
from collections import deque
import threading
import time
import wave

import pyaudio
from loguru import logger
from src.audio_runtime import (
    create_audio_interface,
    terminate_audio_interface,
    release_audio_thread,
    reopen_audio_interface,
    default_audio_endpoints,
)


class AudioFeedbackPlayer:
    def __init__(self, paths):
        self.paths = paths
        self.sounds = {}
        self.pending = deque()
        self.remaining = b""
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.started = threading.Event()
        self.error = None
        self.closed = threading.Event()
        self.channels = 2
        self.underruns = 0
        self.last_callback = 0.0
        self.thread = threading.Thread(
            target=self._run, daemon=True, name="AudioFeedback"
        )
        self.thread.start()

    def _load_sound(self, path, rate):
        with wave.open(str(path), "rb") as sound:
            if sound.getsampwidth() != 2 or sound.getnchannels() != 1:
                raise ValueError("Feedback must use 16-bit mono PCM WAV files")
            source_rate = sound.getframerate()
            samples = array("h", sound.readframes(sound.getnframes()))
        output = array("h")
        for index in range(round(len(samples) * rate / source_rate)):
            position = index * source_rate / rate
            left = min(int(position), len(samples) - 1)
            right = min(left + 1, len(samples) - 1)
            sample = round(
                samples[left] + (samples[right] - samples[left]) * (position - left)
            )
            output.extend([sample] * self.channels)
        return output.tobytes()

    def _run(self):
        recovering = False
        try:
            while not self.closed.is_set():
                retry_delay = 0.25
                try:
                    self._run_stream(recovering)
                except Exception as error:
                    previous_error = self.error
                    self.error = error
                    if not self.started.is_set():
                        self.started.set()
                        logger.error(
                            f"Windows feedback output could not start: {error}"
                        )
                        return
                    if previous_error is None or str(previous_error) != str(error):
                        logger.warning(f"Feedback output will reconnect: {error}")
                    retry_delay = 1.0
                recovering = True
                if self.closed.wait(retry_delay):
                    break
        finally:
            release_audio_thread()

    def _run_stream(self, recovering):
        interface = None
        stream = None
        try:
            interface = (
                reopen_audio_interface() if recovering else create_audio_interface()
            )
            if interface is None:
                return  # A capture is active; retry after it has finished.
            endpoints = default_audio_endpoints()
            try:
                device = interface.get_host_api_info_by_type(pyaudio.paWASAPI)[
                    "defaultOutputDevice"
                ]
                if device < 0:
                    raise OSError("No default WASAPI output")
            except (OSError, ValueError):
                device = interface.get_default_output_device_info()["index"]
            info = interface.get_device_info_by_index(int(device))
            rate = int(info["defaultSampleRate"])
            self.channels = min(2, int(info["maxOutputChannels"]))
            if self.channels < 1:
                raise OSError("The default device has no output channels")
            self.sounds = {
                str(path): self._load_sound(path, rate) for path in self.paths
            }
            self.last_callback = time.monotonic()
            stream = interface.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=rate,
                output=True,
                output_device_index=int(device),
                frames_per_buffer=512,
                stream_callback=self._callback,
            )
            logger.info(
                f"Feedback output ready: {info['name']} ({rate} Hz); persistent stream"
            )
            self.ready.set()
            self.started.set()
            self.error = None
            while not self.closed.wait(0.25):
                if self._stream_needs_reopen(stream, endpoints):
                    break
        finally:
            self.ready.clear()
            with self.lock:
                # A device transition must not replay old cues on the new device.
                self.pending.clear()
                self.remaining = b""
            if stream is not None:
                try:
                    stream.stop_stream()
                except Exception as error:
                    logger.warning(f"Feedback output stop failed: {error}")
                try:
                    stream.close()
                except Exception as error:
                    logger.warning(f"Feedback output close failed: {error}")
            if interface is not None:
                terminate_audio_interface(interface)

    def _stream_needs_reopen(self, stream, endpoints):
        if default_audio_endpoints() != endpoints:
            logger.info("Windows audio endpoint changed; refreshing chime output")
            return True
        if not stream.is_active() or time.monotonic() - self.last_callback > 2:
            logger.warning("Chime output stopped responding; reopening the stream")
            return True
        return False

    def _callback(self, input_data, frame_count, time_info, status_flags):
        self.last_callback = time.monotonic()
        if self.closed.is_set():
            return b"\x00" * frame_count * self.channels * 2, pyaudio.paComplete
        if status_flags & pyaudio.paOutputUnderflow:
            self.underruns += 1
        needed = frame_count * self.channels * 2
        output = bytearray()
        with self.lock:
            while len(output) < needed:
                if not self.remaining:
                    if not self.pending:
                        break
                    self.remaining = self.pending.popleft()
                take = min(needed - len(output), len(self.remaining))
                output.extend(self.remaining[:take])
                self.remaining = self.remaining[take:]
        output.extend(b"\x00" * (needed - len(output)))
        return bytes(output), pyaudio.paContinue

    def play(self, path):
        with self.lock:
            sound = self.sounds.get(str(path))
            if not self.ready.is_set() or not sound or len(self.pending) >= 4:
                return False
            self.pending.append(sound)
        if self.underruns:
            logger.warning(
                f"Audio feedback output reported {self.underruns} underrun(s)"
            )
            self.underruns = 0
        return True

    def close(self):
        self.closed.set()
        self.thread.join(timeout=3)
