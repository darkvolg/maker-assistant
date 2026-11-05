import json
import logging
import platform
import sys
from pathlib import Path
import typer
from rich.console import Console
from assistant.config import load_config
from assistant.core.brain import Brain
from assistant.core.tts import TextToSpeech
from assistant.skills import components, smart_home, system_tools, github_tools
from assistant.skills.registry import registry

app = typer.Typer(help="Голосовой помощник для мастерской", no_args_is_help=True)
console = Console()


def message(config, ru, en):
    return en if config.get("assistant", {}).get("language") == "en" else ru


def setup(config_file):
    config = load_config(config_file)
    for module in (components, smart_home, github_tools):
        module.configure(config)
    registry.configure(config)
    return config


@app.command()
def chat(config_file: str = "config.yaml", mute: bool = False):
    """Текстовый диалог. --mute отключает озвучку."""
    config = setup(config_file)
    if mute:
        config["tts"]["engine"] = "console"
    brain, tts = Brain(config), TextToSpeech(config)
    system_tools.set_tts_notifier(tts.speak)
    console.print(message(config, "Maker Assistant · найди ESP32 · взял 2 · подтверждаю · отмени · exit", "Maker Assistant · find ESP32 · take two · confirm · undo · exit"))
    try:
        while True:
            query = console.input(message(config, "Вы: ", "You: ")).strip()
            if query.lower() in ("exit", "quit", "выход"):
                break
            if query:
                result = brain.process(query)
                console.print(result, markup=False)
                if not mute:
                    tts.speak(result)
                    tts.wait()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        system_tools.set_tts_notifier(None)
        tts.close()


@app.command()
def listen(config_file: str = "config.yaml", microphone: str = "auto"):
    """Голосовой режим: «Джарвис, найди ESP32» одной фразой."""
    from assistant.core.stt import SpeechRecognizer
    from assistant.core.wake_word import WakeWordDetector
    from assistant.utils.audio import AudioRecorder
    config = setup(config_file)
    ac = config.get("audio", {})
    stt = SpeechRecognizer(config)
    brain, tts = Brain(config), TextToSpeech(config)
    system_tools.set_tts_notifier(tts.speak)
    device = ac.get("input_device") if microphone == "auto" else int(microphone) if microphone.isdigit() else microphone
    recorder = AudioRecorder(device=device)
    detector = WakeWordDetector(config["assistant"]["wake_word"], config["assistant"].get("wake_aliases", []))
    follow_up = False
    tts.speak(message(config, "Ассистент готов. Назови моё имя и команду.", "Assistant ready. Say my name followed by a command."))
    tts.wait()
    console.print(message(config, "Голосовой режим. Ctrl+C — выход. Каждую команду начинай со слова активации.", "Voice mode. Ctrl+C to exit. Start every command with the wake word."))
    try:
        while True:
            audio = recorder.record_until_silence(
                energy_threshold=ac.get("energy_threshold",0.015),
                silence_timeout=ac.get("silence_timeout_sec",0.8))
            if not len(audio):
                follow_up = False
                continue
            text = stt.transcribe(audio)
            command = detector.extract_command(text)
            if command is None and follow_up:
                command = text
            follow_up = False
            if command is None:
                continue
            if not command:
                tts.speak(message(config, "Слушаю.", "Listening."))
                tts.wait()
                follow_up = True
                continue
            console.print(message(config, f"Вы: {command}", f"You: {command}"), markup=False)
            response = brain.process(command)
            console.print(response, markup=False)
            tts.speak(response)
            tts.wait()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        console.print(message(config, f"Голосовой режим остановлен: {exc}. Запусти doctor.", f"Voice mode stopped: {exc}. Run doctor."), markup=False)
        raise typer.Exit(1)
    finally:
        system_tools.set_tts_notifier(None)
        tts.close()


@app.command("import-inventory")
def import_inventory(path: Path, config_file: str = "config.yaml"):
    """Импорт JSON в пустую базу. Пример: examples/sklad_example.json."""
    setup(config_file)
    try:
        console.print(f"Импортировано позиций: {components.import_inventory(path)}")
    except (ValueError, KeyError, OSError) as exc:
        console.print(str(exc), markup=False)
        raise typer.Exit(1)


@app.command()
def devices():
    """Список микрофонов и выходов PortAudio."""
    import sounddevice as sd
    console.print(str(sd.query_devices()), markup=False)


@app.command()
def doctor(config_file: str = "config.yaml", audio_test: bool = False, stt_test: bool = False):
    """Проверка окружения. Дополнительно: --audio-test --stt-test."""
    import importlib.metadata
    import requests
    config = setup(config_file)
    failures = []
    console.print(f"Python {platform.python_version()} · {sys.executable}", markup=False)
    for package in ("faster-whisper", "ctranslate2", "sounddevice", "pywin32"):
        try:
            console.print(f"{package}: {importlib.metadata.version(package)}")
        except importlib.metadata.PackageNotFoundError:
            console.print(f"{package}: не установлен")
    bc = config["brain"]
    if bc["provider"] == "ollama":
        try:
            base = bc["base_url"].removesuffix("/v1")
            r = requests.get(base+"/api/tags", timeout=5)
            r.raise_for_status()
            models = [m["name"] for m in r.json()["models"]]
            found = bc["model"] in models
            console.print(f"Ollama: доступен; {bc['model']}: {'OK' if found else 'НЕТ'}")
            if not found:
                failures.append("Не установлена модель Ollama")
        except Exception:
            failures.append("Ollama недоступен; базовые команды работают без него")
    console.print(f"Склад: {config['skills']['components']['storage_path']}", markup=False)
    if config["tts"]["engine"] == "sapi":
        try:
            import win32com.client
            voices = [v.GetDescription() for v in win32com.client.Dispatch("SAPI.SpVoice").GetVoices()]
            console.print("SAPI: " + "; ".join(voices))
            if not any(config["tts"].get("sapi_voice", "Irina").lower() in v.lower() for v in voices):
                failures.append("Выбранный голос SAPI не найден")
        except Exception:
            failures.append("SAPI недоступен; Windows + pywin32 требуются для офлайн-голоса")
    try:
        import sounddevice as sd
        from assistant.utils.audio import resolve_input
        device, info = resolve_input(config.get("audio",{}).get("input_device"))
        rate = int(info["default_samplerate"])
        console.print(f"Микрофон: {info['name']} / {rate} Hz", markup=False)
        sd.check_input_settings(device=device, channels=1, samplerate=rate, dtype="float32")
        if audio_test:
            import numpy as np
            import time
            samples = []
            def capture(indata, frames, timing, status):
                samples.append(indata.copy())
            with sd.InputStream(device=device, channels=1, samplerate=rate, dtype="float32", callback=capture):
                time.sleep(1)
            if not samples:
                raise RuntimeError("Микрофон не передаёт звук")
            frames = np.concatenate(samples)
            console.print(f"Захват 1 с: RMS={float(np.sqrt(np.mean(frames**2))):.5f}")
    except Exception as exc:
        failures.append(f"Микрофон: {exc}")
    if stt_test:
        try:
            import numpy as np
            from assistant.core.stt import SpeechRecognizer
            stt = SpeechRecognizer(config)
            stt.transcribe(np.zeros(16000, dtype=np.float32))
            console.print(f"STT: {stt.model_size} / {stt.device} / {stt.compute_type}: OK")
        except Exception as exc:
            failures.append(f"STT: {exc}")
    for failure in failures:
        console.print(f"ПРОВЕРЬ: {failure}", markup=False)
    if failures:
        raise typer.Exit(1)
    console.print("Проверки пройдены. Это не заменяет испытание речи в шумной мастерской.")


@app.command("download-model")
def download_model(config_file: str = "config.yaml"):
    """Однократно загрузить выбранную Whisper-модель для офлайн-работы."""
    from faster_whisper.utils import download_model as download
    config = load_config(config_file)
    console.print(download(config["stt"]["model_size"]))


@app.command("test-voice")
def test_voice(config_file: str = "config.yaml"):
    """Произнести тестовую фразу выбранным голосом."""
    config = load_config(config_file)
    tts = TextToSpeech(config)
    tts.speak(message(config, "Проверка голоса. Помощник для мастерской готов к работе.", "Voice test. Your workbench assistant is ready."))
    tts.close()
