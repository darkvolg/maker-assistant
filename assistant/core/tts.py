import os
import asyncio
import tempfile
import logging
from typing import Dict, Any

logger = logging.getLogger("maker_assistant.tts")

class TextToSpeech:
    def __init__(self, config: Dict[str, Any]):
        tts_cfg = config.get("tts", {})
        self.engine = tts_cfg.get("engine", "edge-tts")
        self.voice = tts_cfg.get("voice", "ru-RU-DmitryNeural")
        self.rate = tts_cfg.get("rate", "+10%")
        self.volume = tts_cfg.get("volume", "+0%")
        self._pygame_inited = False

    def _ensure_audio_player(self):
        if not self._pygame_inited:
            try:
                import pygame
                pygame.mixer.init()
                self._pygame_inited = True
            except Exception as e:
                logger.error(f"Failed to init pygame.mixer: {e}")

    async def _generate_audio_file(self, text: str, output_path: str):
        import edge_tts
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume
        )
        await communicate.save(output_path)

    def speak(self, text: str):
        if not text:
            return

        logger.info(f"Speaking: '{text}'")
        if self.engine == "console":
            print(f"\n[Ассистент]: {text}\n")
            return

        try:
            import edge_tts
            import pygame

            self._ensure_audio_player()
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                temp_filename = f.name

            # Run async edge-tts
            asyncio.run(self._generate_audio_file(text, temp_filename))

            # Play audio
            pygame.mixer.music.load(temp_filename)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)

            pygame.mixer.music.unload()
            try:
                os.remove(temp_filename)
            except OSError:
                pass

        except Exception as e:
            logger.warning(f"TTS audio fallback ({e}).")
            print(f"\n[Ассистент (текст)]: {text}\n")
