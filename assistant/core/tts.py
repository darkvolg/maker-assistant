import os
import asyncio
import tempfile
import logging
import threading
import queue
import time
from typing import Dict, Any, Optional

logger = logging.getLogger("maker_assistant.tts")

# Глобальный Event: установлен (set), когда ассистент говорит вслух
is_speaking_event = threading.Event()

class TextToSpeech:
    def __init__(self, config: Dict[str, Any]):
        tts_cfg = config.get("tts", {})
        self.engine = tts_cfg.get("engine", "edge-tts")
        self.voice = tts_cfg.get("voice", "ru-RU-DmitryNeural")
        self.rate = tts_cfg.get("rate", "+10%")
        self.volume = tts_cfg.get("volume", "+0%")
        self._pygame_inited = False
        
        # Потокобезопасная очередь для синтеза речи (таймеры + ответы LLM)
        self._speech_queue: queue.Queue[str] = queue.Queue()
        self._worker_thread = threading.Thread(target=self._speech_worker, daemon=True)
        self._worker_thread.start()

    def _ensure_audio_player(self):
        if not self._pygame_inited:
            try:
                import pygame
                pygame.mixer.init()
                self._pygame_inited = True
            except Exception as e:
                logger.error(f"Failed to init pygame.mixer: {e}")

    async def _generate_edge_tts(self, text: str, output_path: str):
        import edge_tts
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume
        )
        await asyncio.wait_for(communicate.save(output_path), timeout=3.0)

    def _speak_offline_sapi(self, text: str) -> bool:
        """100% локальный офлайн-синтез через системный Windows SAPI5."""
        try:
            import win32com.client
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Speak(text)
            return True
        except Exception:
            try:
                # Фоллбек через PowerShell SAPI
                import subprocess
                ps_cmd = f"Add-Type -AssemblyName System.speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{text}')"
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], timeout=5, check=True)
                return True
            except Exception as e:
                logger.error(f"Offline SAPI failed: {e}")
                return False

    def _play_audio_file(self, file_path: str):
        """Проигрывает аудио и гарантирует выгрузку дескриптора на Windows."""
        import pygame
        self._ensure_audio_player()
        try:
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(15)
        finally:
            try:
                pygame.mixer.music.unload()  # Освобождаем файл на Windows!
            except Exception:
                pass

    def _process_single_utterance(self, text: str):
        """Обрабатывает одну речевую фразу с Half-Duplex блокировкой микрофона."""
        if not text or not text.strip():
            return

        logger.info(f"Speaking: '{text}'")

        # 1. Активируем Half-Duplex Lock (микрофон глушится)
        is_speaking_event.set()
        temp_filename = None

        try:
            played = False

            # Попытка Edge-TTS с таймаутом 3.0 сек
            if self.engine != "console":
                try:
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                        temp_filename = f.name

                    asyncio.run(self._generate_edge_tts(text, temp_filename))
                    self._play_audio_file(temp_filename)
                    played = True
                except Exception as net_err:
                    logger.warning(f"Edge-TTS unavailable or timed out ({net_err}). Switching to offline SAPI5...")

            # Офлайн фоллбек, если Edge-TTS не сработал
            if not played and self.engine != "console":
                played = self._speak_offline_sapi(text)

            # Консольный фоллбек
            if not played:
                print(f"\n[Ассистент]: {text}\n")

        finally:
            # Очистка временного файла
            if temp_filename and os.path.exists(temp_filename):
                try:
                    os.remove(temp_filename)
                except OSError:
                    pass

            # Задержка 0.3 сек для затухания реверберации в комнате перед открытием микрофона
            time.sleep(0.3)
            is_speaking_event.clear()

    def _speech_worker(self):
        """Фоновый рабочий поток, обрабатывающий очередь речи без наложения голосов."""
        while True:
            text = self._speech_queue.get()
            try:
                self._process_single_utterance(text)
            except Exception as e:
                logger.error(f"Error in TTS worker: {e}")
            finally:
                self._speech_queue.task_done()

    def speak(self, text: str):
        """Публичный неблокирующий метод добавления фразы в очередь речи."""
        if text:
            self._speech_queue.put(text)
