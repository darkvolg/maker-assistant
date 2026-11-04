import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import pytest
from assistant.config import load_config
from assistant.cli import setup
from assistant.core.brain import Brain
from assistant.core.wake_word import WakeWordDetector
from assistant.skills import components, github_tools, smart_home, system_tools
from assistant.skills.registry import registry


@pytest.fixture
def bench(tmp_path):
    config = setup("config.yaml")
    config["brain"]["provider"] = "none"
    config["skills"]["components"]["storage_path"] = str(tmp_path / "stock.sqlite3")
    components.configure(config)
    components.import_inventory("examples/sklad_example.json")
    yield Brain(config)
    registry.configure(setup("config.yaml"))


def qty():
    with components._connect() as db:
        return db.execute("SELECT qty FROM components WHERE name LIKE 'ESP32%' ").fetchone()[0]


def test_search_normalizes_value_and_package(bench):
    assert "150" in bench.process("Где резисторы 10 кОм 0805?")
    assert "150" in bench.process("найди 10k 0805")


@pytest.mark.parametrize("count", [-2, 0, True, "2", 1.5])
def test_invalid_count_cannot_change_stock(bench, count):
    with pytest.raises(ValueError):
        components.consume_component("ESP32", count)
    assert qty() == 5


def test_confirm_consume_and_undo(bench):
    assert "5 шт" in bench.process("найди ESP32")
    assert "Подтверди" in bench.process("взял два")
    assert qty() == 5
    assert "Осталось 3" in bench.process("подтверждаю")
    assert "Подтверди" in bench.process("отмени")
    assert "Возвращено 2" in bench.process("подтверждаю")
    assert qty() == 5
    assert "Нет команды" in bench.process("подтверждаю")


def test_cancel_and_new_request_clear_pending(bench):
    bench.process("спиши 2 ESP32")
    bench.process("отмена")
    bench.process("подтверждаю")
    assert qty() == 5
    bench.process("спиши 2 ESP32")
    bench.process("который час")
    bench.process("подтверждаю")
    assert qty() == 5


def test_expired_confirmation(bench):
    bench.process("спиши 2 ESP32")
    name,args,started = bench.pending
    bench.pending = name,args,started-60
    assert "Нет команды" in bench.process("подтверждаю")
    assert qty() == 5


def test_ambiguous_does_not_consume(bench):
    assert "Уточни" in components.consume_component("резистор", 2)
    assert "Уточни" in components.consume_component("", 2)


def test_concurrent_consumption_no_negative_stock(bench):
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: components.consume_component("ESP32", 1), range(12)))
    assert qty() == 0
    for _ in range(5):
        components.undo_consumption()
    assert qty() == 5


def test_import_refuses_existing_data(bench):
    with pytest.raises(ValueError):
        components.import_inventory("examples/sklad_example.json")
    assert qty() == 5


def test_disabled_skills_and_argument_types(bench):
    assert "недоступен" in registry.execute("ha_turn_on", {"entity_id":"switch.test"})
    assert "не выполнено" in registry.execute("consume_component", {"query":"ESP32","count":"2"})
    assert qty() == 5


def test_git_commit_failure_stops_push():
    with patch.object(github_tools, "_run_safe_cmd", side_effect=[(0,"file.py"),(1,"hook rejected")]) as run:
        assert "не создан" in github_tools.git_commit_push("test")
        assert len(run.call_args_list) == 2
        assert all("push" not in call.args[0] for call in run.call_args_list)


def test_git_does_not_stage_files():
    with patch.object(github_tools, "_run_safe_cmd", return_value=(0,"")) as run:
        assert "Нет подготовленных" in github_tools.git_commit_push("test")
        assert "add" not in run.call_args.args[0]


def test_ha_allowlist_and_no_fake_success():
    smart_home.configure({"skills":{"smart_home":{"allowed_entities":["switch.lab"]}}})
    with patch.object(smart_home.requests,"post") as post:
        assert "не настроен" in smart_home.ha_turn_on("switch.lab")
        assert "отсутствует" in smart_home.ha_turn_off("switch.other")
        post.assert_not_called()


def test_ha_off_uses_actual_service():
    smart_home.configure({"skills":{"smart_home":{"allowed_entities":["switch.lab"],"ha_url":"http://ha","ha_token":"test"}}})
    with patch.object(smart_home.requests,"post") as post:
        assert "принял" in smart_home.ha_turn_off("switch.lab")
        assert post.call_args.args[0] == "http://ha/api/services/switch/turn_off"


def test_wake_word_preserves_command_and_boundaries():
    d = WakeWordDetector()
    assert d.extract_command("Джарвис, найди ESP32") == "найди ESP32"
    assert d.extract_command("джарвис") == ""
    assert d.extract_command("суперджарвис") is None
    assert d.extract_command("где ESP32") is None


def test_model_malformed_action_does_not_run(bench):
    bench.provider = "ollama"
    with patch("assistant.core.brain.requests.post") as post:
        post.return_value.json.return_value = {"choices":[{"message":{"content":'{"action":"consume_component","arguments":{"count":"2"}}'}}]}
        assert "не выполнено" in bench.process("Сделай что-нибудь")
    assert qty() == 5


def test_local_commands_do_not_contact_network(bench):
    with patch("assistant.core.brain.requests.post") as post:
        bench.process("найди ESP32")
        bench.process("который час")
        post.assert_not_called()


def test_sapi_mode_never_calls_edge():
    from assistant.core.tts import TextToSpeech
    tts = TextToSpeech({"tts":{"engine":"sapi"}})
    with patch.object(tts,"_generate_edge_tts") as edge, patch.object(tts,"_speak_offline_sapi",return_value=True) as sapi:
        tts.speak("Text with 'quotes'; $(commands)")
        tts.wait()
        edge.assert_not_called()
        sapi.assert_called_once()
    tts.close()


@pytest.mark.parametrize("seconds", [-1,0,86401,True])
def test_timer_rejects_invalid_duration(seconds):
    with pytest.raises(ValueError):
        system_tools.set_timer(seconds)


def test_config_paths_and_local_overrides(tmp_path):
    (tmp_path/"config.yaml").write_text("skills: {}\nbrain: {provider: none}\n",encoding="utf-8")
    (tmp_path/"config.local.yaml").write_text("audio: {input_device: fifine}\n",encoding="utf-8")
    config = load_config(tmp_path/"config.yaml")
    assert config["audio"]["input_device"] == "fifine"
    assert Path(config["skills"]["components"]["storage_path"]).parent == tmp_path/"data"


def test_numeric_nominal_not_substring(bench):
    with components._connect() as db:
        db.execute("INSERT INTO components(name,package,qty,location) VALUES('Резистор 110 кОм','0805',5,'test')")
    result = components.check_component("10k 0805")
    assert "110" not in result
    assert "150" in result


def test_timer_really_notifies():
    import threading
    event = threading.Event()
    received = []
    def notify(message):
        received.append(message)
        event.set()
    system_tools.set_tts_notifier(notify)
    try:
        system_tools.set_timer(1, "тест")
        assert event.wait(3)
        assert "тест" in received[0]
    finally:
        system_tools.set_tts_notifier(None)


def test_audio_resamples_and_keeps_start(monkeypatch):
    import numpy as np
    from assistant.utils.audio import AudioRecorder
    from assistant.utils import audio
    from types import SimpleNamespace
    monkeypatch.setattr(audio, "resolve_input", lambda device: (0,{"default_samplerate":48000}))
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
        def __enter__(self):
            for level in [0,0.1,0.1,0,0,0,0,0,0,0,0,0]:
                self.callback(np.full((4800,1),level,dtype=np.float32),4800,None,SimpleNamespace(input_overflow=False))
            return self
        def __exit__(self,*args):
            pass
    monkeypatch.setattr(audio.sd,"InputStream",Stream)
    recorded = AudioRecorder().record_until_silence(silence_timeout=0.3,max_duration=1)
    assert recorded.dtype == np.float32
    assert 7000 < len(recorded) < 13000
    assert recorded.max() > 0.09


def test_audio_overflow_discards_command(monkeypatch):
    import numpy as np
    from assistant.utils.audio import AudioRecorder
    from assistant.utils import audio
    from types import SimpleNamespace
    monkeypatch.setattr(audio, "resolve_input", lambda device: (0,{"default_samplerate":16000}))
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
        def __enter__(self):
            self.callback(np.ones((1600,1),dtype=np.float32),1600,None,SimpleNamespace(input_overflow=True))
            return self
        def __exit__(self,*args):
            pass
    monkeypatch.setattr(audio.sd,"InputStream",Stream)
    assert len(AudioRecorder().record_until_silence(max_duration=1)) == 0


def test_explicit_wake_alias():
    assert WakeWordDetector(aliases=["джорвис"]).extract_command("Джорвис, подтверждаю.") == "подтверждаю."
    assert WakeWordDetector().extract_command("Джорвис, подтверждаю.") is None
