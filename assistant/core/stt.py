import os
import sys
import logging
import numpy as np
from typing import Dict, Any

logger = logging.getLogger("maker_assistant.stt")

# Ensure CUDA DLLs are found on Windows
_CUDA_DIRS = [
    r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin",
    r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4\bin",
    r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.2\bin",
    r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin",
]
for _d in _CUDA_DIRS:
    if os.path.isdir(_d):
        os.environ["PATH"] = _d + ";" + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(_d)
            except Exception:
                pass


class SpeechRecognizer:
    def __init__(self, config: Dict[str, Any]):
        self.config = config.get("stt", {})
        self.model_size = self.config.get("model_size", "medium")
        self.device = self.config.get("device", "cuda")
        self.compute_type = self.config.get("compute_type", "float16")
        self.beam_size = self.config.get("beam_size", 5)
        self.language = config.get("assistant", {}).get("language", "ru")

        logger.info(f"Loading faster-whisper [{self.model_size}] on {self.device} ({self.compute_type})...")
        
        self.model = self._init_model(device=self.device, compute_type=self.compute_type)

    def _init_model(self, device: str, compute_type: str):
        from faster_whisper import WhisperModel
        # 1. Попытка стандартной загрузки
        try:
            return WhisperModel(self.model_size, device=device, compute_type=compute_type)
        except Exception as e:
            logger.warning(f"Standard init failed: {e}. Trying with local_files_only=True (Offline mode)...")

        # 2. Попытка загрузки в строгом офлайн-режиме (без связи с HuggingFace)
        try:
            return WhisperModel(self.model_size, device=device, compute_type=compute_type, local_files_only=True)
        except Exception as e:
            logger.warning(f"Offline init failed on {device}: {e}. Falling back to CPU...")

        # 3. Фоллбек на CPU
        self.device = "cpu"
        self.compute_type = "int8"
        try:
            return WhisperModel(self.model_size, device="cpu", compute_type="int8", local_files_only=True)
        except Exception:
            return WhisperModel(self.model_size, device="cpu", compute_type="int8")

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
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return ""
