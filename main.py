import logging
import sys
import typer
from rich.console import Console
from rich.panel import Panel

from assistant.config import load_config
from assistant.core.stt import SpeechRecognizer
from assistant.core.tts import TextToSpeech
from assistant.core.brain import Brain
from assistant.core.wake_word import WakeWordDetector
from assistant.utils.audio import AudioRecorder

# Import skills so they register
import assistant.skills.components
import assistant.skills.smart_home
import assistant.skills.system_tools
import assistant.skills.github_tools

app = typer.Typer(help="100% Local, Always-On Voice AI Assistant for Hardware Engineers & Makers")
console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

@app.command()
def chat(config_file: str = "config.yaml"):
    """
    Interactive text console to test Brain and Skills without microphone.
    """
    config = load_config(config_file)
    brain = Brain(config)
    tts = TextToSpeech(config)

    console.print(Panel.fit(
        "[bold green]Maker Assistant (Text Mode)[/bold green]\n"
        "Тестирование команд без микрофона.\n"
        "Примеры:\n"
        "- 'Есть ли на складе ESP32?'\n"
        "- 'Спиши 1 шт ESP32 для проекта'\n"
        "- 'Который час?'\n"
        "- 'Выключи телевизор'\n"
        "Введите 'exit' для выхода.",
        border_style="cyan"
    ))

    while True:
        try:
            query = console.input("\n[bold yellow]Вы:[/bold yellow] ").strip()
            if not query:
                continue
            if query.lower() in ("exit", "quit", "выход"):
                break

            response = brain.process(query)
            console.print(f"[bold cyan]Ассистент:[/bold cyan] {response}")
            tts.speak(response)

        except KeyboardInterrupt:
            break

    console.print("\n[dim]Сеанс завершен.[/dim]")

@app.command()
def listen(config_file: str = "config.yaml"):
    """
    Always-On Voice mode: waits for Wake-Word and executes actions hands-free.
    """
    config = load_config(config_file)
    wake_word = config.get("assistant", {}).get("wake_word", "джарвис")

    console.print(Panel.fit(
        f"[bold green]Maker Assistant (Always-On Voice Mode)[/bold green]\n"
        f"Wake-Word: '[bold yellow]{wake_word}[/bold yellow]'\n"
        f"STT: {config.get('stt', {}).get('engine')} ({config.get('stt', {}).get('model_size')})\n"
        f"TTS: {config.get('tts', {}).get('engine')}\n"
        f"LLM: {config.get('brain', {}).get('provider')} ({config.get('brain', {}).get('model')})\n"
        f"Нажмите Ctrl+C для выхода.",
        border_style="magenta"
    ))

    stt = SpeechRecognizer(config)
    tts = TextToSpeech(config)
    brain = Brain(config)
    recorder = AudioRecorder(sample_rate=config.get("audio", {}).get("sample_rate", 16000))
    detector = WakeWordDetector(wake_word=wake_word)

    tts.speak("Ассистент готов к работе.")

    while True:
        try:
            console.print(f"\n[dim]🎧 Ожидание слова активации ('{wake_word}')...[/dim]")
            
            # 1. Wait for wake word
            detector.wait_for_activation(check_speech_callback=stt.transcribe)
            
            console.print("[bold green]🔔 Слово активации распознано! Слушаю команду...[/bold green]")
            recorder.play_beep(freq=880, duration=0.1)

            # 2. Record full command until silence
            audio = recorder.record_until_silence(
                energy_threshold=config.get("audio", {}).get("energy_threshold", 0.015),
                silence_timeout=config.get("audio", {}).get("silence_timeout_sec", 1.2)
            )

            if len(audio) == 0:
                continue

            # 3. Transcribe speech
            command_text = stt.transcribe(audio)
            if not command_text:
                continue

            console.print(f"[bold yellow]Вы сказали:[/bold yellow] {command_text}")

            # 4. Brain & Skill Execution
            response = brain.process(command_text)
            console.print(f"[bold cyan]Ответ:[/bold cyan] {response}")

            # 5. Speak back
            tts.speak(response)

        except KeyboardInterrupt:
            console.print("\n[dim]Остановка ассистента...[/dim]")
            break

if __name__ == "__main__":
    app()
