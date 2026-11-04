import time
import logging
import numpy as np
import sounddevice as sd
from typing import Callable, Optional

logger = logging.getLogger("maker_assistant.wakeword")

class WakeWordDetector:
    def __init__(self, wake_word: str = "джарвис", sample_rate: int = 16000, energy_threshold: float = 0.015):
        self.wake_word = wake_word.lower().strip()
        self.sample_rate = sample_rate
        self.energy_threshold = energy_threshold
        self._running = False

    def wait_for_activation(self, check_speech_callback: Callable[[np.ndarray], str]) -> bool:
        """
        Continuously listens in lightweight chunks until speech with wake-word is detected.
        """
        chunk_seconds = 1.8
        chunk_size = int(self.sample_rate * chunk_seconds)
        step_size = int(self.sample_rate * 0.5)

        buffer = np.zeros(chunk_size, dtype=np.float32)

        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32") as stream:
            while True:
                step, _ = stream.read(step_size)
                buffer = np.roll(buffer, -step_size)
                buffer[-step_size:] = step.flatten()

                energy = float(np.sqrt(np.mean(buffer[-step_size:]**2)))
                if energy > self.energy_threshold:
                    # Potential voice detected, verify with fast check
                    text = check_speech_callback(buffer).lower()
                    if self.wake_word in text:
                        logger.info(f"Wake word detected: '{self.wake_word}' in '{text}'")
                        return True
