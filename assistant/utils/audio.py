import io
import time
import numpy as np
import sounddevice as sd
from scipy.io import wavfile

class AudioRecorder:
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels

    def record_until_silence(self, energy_threshold: float = 0.015, silence_timeout: float = 1.2, max_duration: float = 15.0) -> np.ndarray:
        """
        Records audio from default microphone until silence is detected.
        Returns float32 audio numpy array.
        """
        chunk_size = int(self.sample_rate * 0.1)  # 100ms chunks
        recorded_chunks = []
        silence_start = None
        start_time = time.time()
        has_spoken = False

        with sd.InputStream(samplerate=self.sample_rate, channels=self.channels, dtype="float32") as stream:
            while True:
                chunk, _ = stream.read(chunk_size)
                energy = float(np.sqrt(np.mean(chunk**2)))
                recorded_chunks.append(chunk)

                if energy > energy_threshold:
                    has_spoken = True
                    silence_start = None
                elif has_spoken:
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start >= silence_timeout:
                        break

                if time.time() - start_time > max_duration:
                    break

        if not recorded_chunks:
            return np.array([], dtype=np.float32)

        return np.concatenate(recorded_chunks, axis=0).flatten()

    @staticmethod
    def play_beep(freq: int = 800, duration: float = 0.1, sample_rate: int = 16000):
        """Short audio feedback chime."""
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        tone = np.sin(freq * t * 2 * np.pi) * 0.2
        # Smooth attack and decay
        fade = int(sample_rate * 0.02)
        if len(tone) > 2 * fade:
            tone[:fade] *= np.linspace(0, 1, fade)
            tone[-fade:] *= np.linspace(1, 0, fade)
        sd.play(tone.astype(np.float32), samplerate=sample_rate)
        sd.wait()
