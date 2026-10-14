import pyaudio
import wave
import threading
import tempfile
from typing import Optional
from loguru import logger
from src.audio_runtime import (
    create_audio_interface,
    terminate_audio_interface,
    initialize_audio_thread,
    release_audio_thread,
)


class AudioRecorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_size: int = 1024,
        channels: int = 1,
        audio_format: int = pyaudio.paInt16,
    ):
        """
        Initialize the audio recorder.

        Args:
            sample_rate: Sample rate in Hz (16kHz is optimal for Whisper)
            chunk_size: Size of audio chunks
            channels: Number of audio channels (1 for mono)
            audio_format: Audio format (16-bit is optimal for Whisper)
        """
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.channels = channels
        self.audio_format = audio_format

        self.is_recording = False
        self.audio_data = []
        self.recording_thread: Optional[threading.Thread] = None

        self.audio_interface = None
        self.stream = None
        self._init_error: Optional[Exception] = None
        self._stream_lock = threading.RLock()
        self._shutting_down = False
        self._refresh_devices = False
        self._capture_rate = sample_rate
        self._capture_channels = channels
        self._capture_ready = threading.Event()

        # Initialize PyAudio in a background thread to avoid blocking startup
        self._init_thread = threading.Thread(
            target=self._initialize_audio_interface, daemon=True
        )
        self._init_thread.start()

    def _initialize_audio_interface(self):
        """Initialize PyAudio interface in background."""
        try:
            interface = create_audio_interface()
            if self._shutting_down:
                terminate_audio_interface(interface)
                return
            self.audio_interface = interface
            logger.debug("PyAudio initialized successfully in background")
        except Exception as e:
            self._init_error = e
            logger.error(f"Failed to initialize PyAudio: {e}")
        finally:
            release_audio_thread()

    def start_recording(self) -> bool:
        """Start recording audio."""
        with self._stream_lock:
            return self._start_recording()

    def _start_recording(self) -> bool:
        initialize_audio_thread()
        if self._shutting_down:
            return False
        if self.is_recording:
            logger.warning("Recording is already in progress")
            return False

        # Ensure initialization is complete
        if not self.audio_interface:
            if self._init_thread and self._init_thread.is_alive():
                logger.info("Waiting for audio interface initialization...")
                self._init_thread.join(timeout=5.0)

            if self._init_error:
                logger.error(
                    f"Cannot start recording, initialization failed: {self._init_error}"
                )
                return False

            if not self.audio_interface:
                logger.error("Audio interface not initialized")
                return False

        try:
            # Refresh cached endpoints after an unplugged microphone made Windows
            # fall back to loopback capture. Never silently dictate desktop audio.
            if self._refresh_devices:
                terminate_audio_interface(self.audio_interface)
                self.audio_interface = create_audio_interface()
                self._refresh_devices = False
            try:
                input_info = self.audio_interface.get_default_input_device_info()
            except OSError:
                terminate_audio_interface(self.audio_interface)
                self.audio_interface = create_audio_interface()
                input_info = self.audio_interface.get_default_input_device_info()
            if "stereo mix" in str(input_info.get("name", "")).lower():
                terminate_audio_interface(self.audio_interface)
                self.audio_interface = create_audio_interface()
                input_info = self.audio_interface.get_default_input_device_info()
                if "stereo mix" in str(input_info.get("name", "")).lower():
                    raise RuntimeError(
                        "Windows selected Stereo Mix instead of a microphone. Reconnect your microphone and select it as the default input."
                    )
            input_device = input_info.get("index")
            self._capture_rate = self.sample_rate
            self._capture_channels = self.channels
            if hasattr(pyaudio, "paWASAPI"):
                try:
                    native_device = int(
                        self.audio_interface.get_host_api_info_by_type(
                            pyaudio.paWASAPI
                        )["defaultInputDevice"]
                    )
                    if native_device < 0:
                        raise OSError("No default WASAPI microphone")
                    input_info = self.audio_interface.get_device_info_by_index(
                        native_device
                    )
                    if "stereo mix" in str(input_info.get("name", "")).lower():
                        raise OSError("Default WASAPI input is loopback")
                    input_device = native_device
                    self._capture_rate = int(input_info["defaultSampleRate"])
                    self._capture_channels = min(2, int(input_info["maxInputChannels"]))
                except (OSError, ValueError):
                    pass
            logger.info(
                f"Recording input: {input_info.get('name', 'system default')} ({self._capture_rate} Hz, {self._capture_channels} channel(s))"
            )
            self.audio_data = []
            self._capture_ready.clear()
            self.is_recording = True
            self.stream = self.audio_interface.open(
                format=self.audio_format,
                channels=self._capture_channels,
                rate=self._capture_rate,
                input=True,
                input_device_index=input_device,
                frames_per_buffer=self.chunk_size,
                stream_callback=self._audio_callback,
                start=False,
            )
            self.stream.start_stream()
            self._capture_ready.wait(timeout=0.15)

            logger.info("Audio recording started")
            return True

        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            self._refresh_devices = True
            self.is_recording = False
            self._cleanup_stream()
            return False

    def stop_recording(self) -> Optional[str]:
        with self._stream_lock:
            return self._stop_recording()

    def _stop_recording(self) -> Optional[str]:
        """
        Stop recording and save audio to a temporary file.

        Returns:
            Path to the temporary audio file, or None if recording failed
        """
        if not self.is_recording:
            logger.warning("No recording in progress")
            return None

        self.is_recording = False

        # Get sample width before cleanup
        sample_width = None
        if self.audio_interface:
            try:
                sample_width = self.audio_interface.get_sample_size(self.audio_format)
            except Exception as e:
                logger.warning(f"Could not get sample size from audio interface: {e}")
                # Fallback: calculate sample width from format
                if self.audio_format == pyaudio.paInt16:
                    sample_width = 2
                elif self.audio_format == pyaudio.paInt32:
                    sample_width = 4
                elif self.audio_format == pyaudio.paFloat32:
                    sample_width = 4
                else:
                    sample_width = 2  # Default to 16-bit

        self._cleanup_stream()

        if not self.audio_data:
            logger.warning("No audio data recorded")
            return None

        if sample_width is None:
            logger.error("Could not determine sample width")
            return None

        # Save audio to temporary file
        try:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
            temp_filename = temp_file.name
            temp_file.close()

            with wave.open(temp_filename, "wb") as wf:
                wf.setnchannels(self._capture_channels)
                wf.setsampwidth(sample_width)
                wf.setframerate(self._capture_rate)
                wf.writeframes(b"".join(self.audio_data))

            logger.info(f"Audio saved to {temp_filename}")
            return temp_filename

        except Exception as e:
            logger.error(f"Failed to save audio: {e}")
            return None

    def _audio_callback(self, input_data, frame_count, time_info, status_flags):
        """Collect callback buffers without a blocking read on another thread.

        Returning paComplete ends capture before the worker stops and closes the
        stream. No PortAudio control methods are called from this callback.
        """
        if not self.is_recording:
            return None, pyaudio.paComplete
        if isinstance(input_data, (bytes, bytearray)):
            self.audio_data.append(input_data)
            self._capture_ready.set()
        return None, pyaudio.paContinue

    def _cleanup_stream(self):
        """Clean up audio stream resources."""
        with self._stream_lock:
            self.is_recording = False
            if self.stream:
                stream, self.stream = self.stream, None
                try:
                    stream.stop_stream()
                except Exception as e:
                    logger.warning(f"Error stopping audio stream: {e}")
                try:
                    stream.close()
                except Exception as e:
                    logger.error(f"Error closing audio stream: {e}")

    def shutdown(self):
        """Terminate audio interface."""
        self._shutting_down = True
        with self._stream_lock:
            self._shutdown()

    def _shutdown(self):
        self._cleanup_stream()

        # Ensure init thread is done if we are shutting down
        if self._init_thread and self._init_thread.is_alive():
            try:
                self._init_thread.join(timeout=1.0)
            except Exception:
                pass

        try:
            if self.audio_interface:
                terminate_audio_interface(self.audio_interface)
                self.audio_interface = None
        except Exception as e:
            logger.error(f"Error during audio interface shutdown: {e}")

    def __enter__(self):
        """Context manager entry - returns self for use in 'with' statements."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cleanup even if exceptions occur."""
        self.shutdown()
        return False  # Don't suppress exceptions
