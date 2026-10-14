"""Keep the Windows output stream ready for immediate, uninterrupted chimes."""

from array import array
from collections import deque
import threading
import wave

import pyaudio
from loguru import logger


class AudioFeedbackPlayer:
    def __init__(self, paths):
        self.paths = paths
        self.sounds = {}
        self.pending = deque()
        self.remaining = b""
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.closed = threading.Event()
        self.channels = 2
        self.underruns = 0
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
        interface = None
        stream = None
        try:
            interface = pyaudio.PyAudio()
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
            self.closed.wait()
        except Exception as error:
            logger.warning(
                f"Persistent feedback unavailable, using native WAV fallback: {error}"
            )
        finally:
            self.ready.clear()
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception as error:
                    logger.warning(f"Feedback output cleanup failed: {error}")
            if interface is not None:
                interface.terminate()

    def _callback(self, input_data, frame_count, time_info, status_flags):
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
        sound = self.sounds.get(str(path))
        if not self.ready.is_set() or not sound:
            return False
        with self.lock:
            if len(self.pending) < 4:
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
