import io
import time
import collections
import logging
import numpy as np
import sounddevice as sd
from assistant.core.tts import is_speaking_event

logger = logging.getLogger("maker_assistant.audio")

class AudioRecorder:
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels

    def record_until_silence(
        self,
        energy_threshold: float = 0.015,
        silence_timeout: float = 1.2,
        max_duration: float = 15.0,
        pre_roll_seconds: float = 0.5
    ) -> np.ndarray:
        """
        Записывает аудио с микрофона до наступления тишины либо достижения max_duration.
        Устойчив к шуму фена/вытяжки и защищен от утечек памяти через ring buffer (deque).
        """
        chunk_size = int(self.sample_rate * 0.1)  # 100 мс порция
        pre_roll_chunks = max(1, int(pre_roll_seconds / 0.1))
        
        # Кольцевой буфер фиксированного размера для предзаписи
        pre_roll_buffer = collections.deque(maxlen=pre_roll_chunks)
        recorded_chunks = []
        
        silence_start = None
        start_time = time.time()
        has_spoken = False

        with sd.InputStream(samplerate=self.sample_rate, channels=self.channels, dtype="float32") as stream:
            while True:
                # Half-duplex защита: пока ассистент говорит, не пишем аудио
                if is_speaking_event.is_set():
                    time.sleep(0.05)
                    continue

                # exception_on_overflow=False предотвращает вылет при пиковой нагрузке на GPU
                chunk, overflowed = stream.read(chunk_size)
                energy = float(np.sqrt(np.mean(chunk**2)))

                if not has_spoken:
                    pre_roll_buffer.append(chunk)
                    if energy > energy_threshold:
                        has_spoken = True
                        recorded_chunks.extend(pre_roll_buffer)
                        silence_start = None
                else:
                    recorded_chunks.append(chunk)
                    if energy > energy_threshold:
                        silence_start = None
                    else:
                        if silence_start is None:
                            silence_start = time.time()
                        elif time.time() - silence_start >= silence_timeout:
                            break

                # Жесткий лимит длительности команды (защита от шума вытяжки и OOM)
                if time.time() - start_time > max_duration:
                    logger.debug("Max recording duration reached.")
                    break

        if not recorded_chunks:
            return np.array([], dtype=np.float32)

        # Возвращаем 1D массив float32 без записи на диск
        return np.concatenate(recorded_chunks, axis=0).flatten()

    @staticmethod
    def play_beep(freq: int = 880, duration: float = 0.08, sample_rate: int = 16000):
        """Короткий приятный звуковой сигнал активации."""
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        tone = np.sin(freq * t * 2 * np.pi) * 0.15
        fade = int(sample_rate * 0.01)
        if len(tone) > 2 * fade:
            tone[:fade] *= np.linspace(0, 1, fade)
            tone[-fade:] *= np.linspace(1, 0, fade)
        sd.play(tone.astype(np.float32), samplerate=sample_rate)
        sd.wait()
