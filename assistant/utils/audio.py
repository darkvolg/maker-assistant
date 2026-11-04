import collections
import logging
import math
import queue
import time
import threading
import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly
from assistant.core.tts import is_speaking_event

logger = logging.getLogger(__name__)


def resolve_input(device=None):
    """Resolve a stable device name or an explicit PortAudio index."""
    if isinstance(device, str):
        matches = [i for i,d in enumerate(sd.query_devices())
                   if d["max_input_channels"] and device.casefold() in d["name"].casefold()]
        if len(matches) != 1:
            raise ValueError(f"Микрофон '{device}': найдено {len(matches)} вариантов; выбери индекс через devices")
        device = matches[0]
    return device, sd.query_devices(device, "input")


class AudioRecorder:
    def __init__(self, sample_rate=16000, channels=1, device=None):
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device

    def record_until_silence(self, energy_threshold=0.015, silence_timeout=0.8,
                             max_duration=15.0, pre_roll_seconds=0.5):
        device, info = resolve_input(self.device)
        rate = int(info["default_samplerate"])
        chunks = queue.Queue(maxsize=32)
        dropped = threading.Event()

        def callback(indata, frames, timing, status):
            if status.input_overflow:
                dropped.set()
            try:
                chunks.put_nowait(indata[:,0].copy())
            except queue.Full:
                dropped.set()

        pre = collections.deque(maxlen=max(1,int(pre_roll_seconds/0.1)))
        recorded = []
        has_spoken = False
        silence = 0.0
        deadline = time.monotonic() + max_duration
        with sd.InputStream(device=device, samplerate=rate, channels=1, dtype="float32",
                            blocksize=int(rate*0.1), callback=callback):
            while time.monotonic() < deadline:
                try:
                    chunk = chunks.get(timeout=0.25)
                except queue.Empty:
                    continue
                if dropped.is_set():
                    logger.warning("Audio overflow: dropping incomplete utterance")
                    return np.array([],dtype=np.float32)
                if is_speaking_event.is_set():
                    pre.clear()
                    recorded.clear()
                    has_spoken = False
                    silence = 0.0
                    continue
                energy = float(np.sqrt(np.mean(chunk**2)))
                if not has_spoken:
                    pre.append(chunk)
                    if energy > energy_threshold:
                        recorded.extend(pre)
                        has_spoken = True
                else:
                    recorded.append(chunk)
                    silence = 0.0 if energy > energy_threshold else silence + len(chunk)/rate
                    if silence >= silence_timeout:
                        break
        if not recorded:
            return np.array([],dtype=np.float32)
        audio = np.concatenate(recorded)
        if rate != self.sample_rate:
            divisor = math.gcd(rate,self.sample_rate)
            audio = resample_poly(audio,self.sample_rate//divisor,rate//divisor)
        return audio.astype(np.float32)
