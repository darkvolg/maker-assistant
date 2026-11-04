"""Opt-in Windows test with real SAPI and cached Whisper; no microphone/network."""
import os
import sys
from pathlib import Path
import pytest

@pytest.mark.skipif(sys.platform != "win32" or os.getenv("MAKER_TEST_VOICE") != "1",
                    reason="Set MAKER_TEST_VOICE=1 on Windows with cached Whisper small")
def test_spoken_inventory_roundtrip(tmp_path):
    import win32com.client
    from faster_whisper.audio import decode_audio
    from assistant.cli import setup
    from assistant.core.brain import Brain
    from assistant.core.stt import SpeechRecognizer
    from assistant.core.wake_word import WakeWordDetector
    from assistant.skills import components
    cfg = setup("config.yaml")
    cfg["brain"]["provider"] = "none"
    cfg["stt"].update(device="cpu", compute_type="int8", local_files_only=True)
    cfg["skills"]["components"]["storage_path"] = str(tmp_path/"inventory.sqlite3")
    components.configure(cfg)
    components.import_inventory("examples/sklad_example.json")
    brain, stt = Brain(cfg), SpeechRecognizer(cfg)
    wake = WakeWordDetector(cfg["assistant"]["wake_word"], cfg["assistant"].get("wake_aliases", []))
    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    speaker.Voice = next(v for v in speaker.GetVoices() if "Irina" in v.GetDescription())
    phrases = ["Джарвис, найди резисторы десять килоом.", "Джарвис, взял четыре.",
               "Джарвис, подтверждаю.", "Джарвис, отмени.", "Джарвис, подтверждаю."]
    try:
        for idx, phrase in enumerate(phrases):
            path = str(tmp_path/f"speech-{idx}.wav")
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            stream.Format.Type = 22
            stream.Open(path, 3)
            try:
                speaker.AudioOutputStream = stream
                speaker.Speak(phrase, 16)
            finally:
                stream.Close()
            heard = stt.transcribe(decode_audio(path,sampling_rate=16000))
            command = wake.extract_command(heard)
            assert command is not None, heard
            response = brain.process(command)
            if idx == 2:
                assert "146" in response
        with components._connect() as db:
            assert db.execute("SELECT qty FROM components WHERE name='Резистор 10 кОм'").fetchone()[0] == 150
            assert db.execute("SELECT count(*) FROM movements WHERE undone=1").fetchone()[0] == 1
    finally:
        setup("config.yaml")
