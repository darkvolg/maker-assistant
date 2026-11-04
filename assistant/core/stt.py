import os
import sys
import logging
import numpy as np
from typing import Dict, Any

logger = logging.getLogger("maker_assistant.stt")

# Ensure CUDA DLLs are found on Windows if installed
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
        try:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type
            )
            logger.info("SpeechRecognizer successfully loaded.")
        except Exception as e:
            logger.warning(f"Failed to load on {self.device}: {e}. Falling back to CPU...")
            from faster_whisper import WhisperModel
            self.model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
            self.device = "cpu"

    def transcribe(self, audio_data: np.ndarray) -> str:
        if audio_data is None or len(audio_data) == 0:
            return ""

        segments, _ = self.model.transcribe(
            audio_data,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500)
        )
        
        text = " ".join([seg.text.strip() for seg in segments]).strip()
        return text
