import os
import sys
import logging
import numpy as np
from typing import Dict, Any

logger = logging.getLogger("maker_assistant.stt")

# Keep DLL directory handles alive throughout the process.
from pathlib import Path
_DLL_HANDLES = []
if os.name == "nt":
    candidates = [Path(os.environ.get("CUDA_PATH", "C:/missing")) / "bin"]
    candidates += list(Path(sys.prefix).glob("Lib/site-packages/nvidia/*/bin"))
    for directory in candidates:
        if directory.is_dir():
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
            _DLL_HANDLES.append(os.add_dll_directory(str(directory)))


class SpeechRecognizer:
    def __init__(self, config: Dict[str, Any]):
        self.config = config.get("stt", {})
        self.model_size = self.config.get("model_size", "medium")
        self.device = self.config.get("device", "cpu")
        self.compute_type = self.config.get("compute_type", "int8")
        self.beam_size = self.config.get("beam_size", 5)
        self.language = config.get("assistant", {}).get("language", "ru")

        logger.info(f"Loading faster-whisper [{self.model_size}] on {self.device} ({self.compute_type})...")
        
        self.model = self._init_model(device=self.device, compute_type=self.compute_type)

    def _init_model(self, device: str, compute_type: str):
        from faster_whisper import WhisperModel
        offline = self.config.get("local_files_only", True)
        try:
            return WhisperModel(self.model_size, device=device, compute_type=compute_type,
                                local_files_only=offline)
        except Exception:
            if device == "cpu":
                raise
            logger.warning("GPU STT unavailable; switching to CPU int8")
            self.device, self.compute_type = "cpu", "int8"
            return WhisperModel(self.model_size, device="cpu", compute_type="int8",
                                local_files_only=offline)

    def transcribe(self, audio_data: np.ndarray) -> str:
        """
        Zero-Disk Transcription: принимает сырой float32 numpy массив прямо из RAM,
        минуя сохранение временных .wav файлов на диск.
        """
        if audio_data is None or len(audio_data) == 0:
            return ""

        # Убеждаемся в float32 и нормализации [-1.0, 1.0]
        if audio_data.dtype != np.float32:
            audio_data = audio_data.astype(np.float32)

        try:
            segments, _ = self.model.transcribe(
                audio_data,
                language=self.language,
                beam_size=self.beam_size,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=400)
            )
            text = " ".join([seg.text.strip() for seg in segments]).strip()
            return text
        except Exception:
            if self.device != "cpu":
                self.device, self.compute_type = "cpu", "int8"
                self.model = self._init_model("cpu", "int8")
                return self.transcribe(audio_data)
            raise
