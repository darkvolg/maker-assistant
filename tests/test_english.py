"""English workflow must execute tools and preserve confirmation safety."""
import json
from unittest.mock import patch
import pytest
from assistant.cli import setup
from assistant.config import load_config
from assistant.core.brain import Brain
from assistant.skills import components, system_tools


@pytest.fixture
def english(tmp_path):
    cfg = setup("config.en.yaml")
    cfg["brain"]["provider"] = "none"
    cfg["skills"]["components"]["storage_path"] = str(tmp_path / "stock.sqlite3")
    components.configure(cfg)
    components.import_inventory("examples/inventory.en.json")
    yield Brain(cfg)
    setup("config.yaml")


def stock():
    with components._connect() as db:
        return db.execute("SELECT qty FROM components WHERE name='10k resistor'").fetchone()[0]


def test_english_inventory_roundtrip(english):
    assert "150 pcs" in english.process("Find 10k resistors")
    assert '"confirm"' in english.process("Take four")
    assert stock() == 150
    assert "Remaining: 146" in english.process("confirm")
    assert '"confirm"' in english.process("undo")
    assert stock() == 146
    assert "Restored 4" in english.process("confirm")
    assert stock() == 150
    assert "No action" in english.process("confirm")


@pytest.mark.parametrize("query", ["Do we have 10k resistors?", "How many 10k resistors do we have?", "Where are 10k resistors?"])
def test_inventory_questions_do_not_require_model(english, query):
    with patch("assistant.core.brain.requests.post", side_effect=AssertionError("No network")):
        assert "150 pcs" in english.process(query)


def test_cancel_expire_and_new_request(english):
    english.process("take two 10k resistors")
    assert "cancelled" in english.process("cancel")
    assert "No action" in english.process("confirm")
    english.process("take two 10k resistors")
    name, args, started = english.pending
    english.pending = name, args, started - 60
    assert "No action" in english.process("confirm")
    english.process("take two 10k resistors")
    assert "It is" in english.process("what time is it")
    assert "No action" in english.process("confirm")
    assert stock() == 150


def test_invalid_and_ambiguous_commands(english):
    assert "positive integer" in english.process("take -2 10k resistors")
    english.process("take two resistors")
    assert "exactly one match" in english.process("confirm")
    english.process("take 999 10k resistors")
    assert "Insufficient stock" in english.process("confirm")
    assert stock() == 150


def test_timer_alert_keeps_language_in_worker(english):
    alerts = []
    system_tools.set_tts_notifier(alerts.append)
    try:
        with patch("assistant.skills.system_tools.time.sleep"):
            assert "300 seconds" in english.process("Set a timer for five minutes")
            system_tools._active_timers[-1].join(timeout=2)
        assert alerts == ["Timer finished: Time is up."]
    finally:
        system_tools.set_tts_notifier(None)


def test_profile_overrides_are_isolated(tmp_path):
    (tmp_path / "config.yaml").write_text("assistant: {language: ru}", encoding="utf-8")
    (tmp_path / "config.en.yaml").write_text("assistant: {language: en}", encoding="utf-8")
    (tmp_path / "config.local.yaml").write_text("assistant: {language: ru}", encoding="utf-8")
    (tmp_path / "config.en.local.yaml").write_text("tts: {engine: console}", encoding="utf-8")
    assert load_config(tmp_path / "config.en.yaml")["assistant"]["language"] == "en"
    assert load_config(tmp_path / "config.en.yaml")["tts"]["engine"] == "console"
    assert load_config(tmp_path / "config.yaml")["assistant"]["language"] == "ru"


def test_model_tool_call_requires_confirmation(english):
    english.provider = "ollama"
    with patch("assistant.core.brain.requests.post") as request:
        request.return_value.json.return_value = {"choices": [{"message": {"content": json.dumps(
            {"action": "consume_component", "arguments": {"query": "10k", "count": 3, "project": "demo"}})}}]}
        assert '"confirm"' in english.process("Deduct parts for my circuit")
    assert stock() == 150
    assert "Remaining: 147" in english.process("confirm")


def test_language_context_does_not_leak(english):
    assert "150 pcs" in english.process("find 10k")
    assert "150 шт." in components.check_component("10k")
