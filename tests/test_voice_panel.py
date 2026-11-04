import hashlib
import json
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import pytest
from voice_panel import Panel, create_server

VOICE = {"id":"test-voice", "engine":"sapi", "name":"Test", "locale":"ru-RU", "gender":"Female"}

@pytest.fixture
def panel(tmp_path):
    (tmp_path/"config.yaml").write_text("tts: {engine: sapi, sapi_voice: Irina}\naudio: {energy_threshold: 0.015}\n",encoding="utf-8")
    (tmp_path/"assets").mkdir()
    (tmp_path/"assets/voice-panel.html").write_text("<html>__PANEL_TOKEN__</html>",encoding="utf-8")
    result = Panel(tmp_path)
    result.voice_cache["sapi"] = [VOICE]
    result.voice_cache["edge-tts"] = [{**VOICE,"id":"ru-RU-TestNeural","engine":"edge-tts"}]
    yield result
    result.close()


def payload(**overrides):
    return {"engine":"sapi","voice":"test-voice","speed":0,"threshold":.015,"device":None,**overrides}


def test_profile_never_modifies_live_config(panel):
    before = (panel.root/"config.yaml").read_bytes()
    result = panel.save_profile(payload())
    assert result["saved"]
    assert panel.profile_path.exists()
    assert (panel.root/"config.yaml").read_bytes() == before
    assert not (panel.root/"config.local.yaml").exists()
    assert panel.current()["draft"]["voice"]["id"] == "test-voice"


@pytest.mark.parametrize("override",[{"speed":31},{"speed":True},{"speed":1},{"threshold":0},{"threshold":float("nan")},{"threshold":True},{"voice":"missing"},{"engine":"unknown"}])
def test_bad_profile_rejected(panel,override):
    with pytest.raises(ValueError):panel.save_profile(payload(**override))
    assert not panel.profile_path.exists()


def test_preview_cache_and_no_live_voices(panel,monkeypatch):
    generated=[]
    def synth(voice,speed,text,path):
        generated.append(text)
        path.write_bytes(b"RIFF-test-wave")
    monkeypatch.setattr(panel,"_sapi",synth)
    before=(panel.root/"config.yaml").read_bytes()
    first=panel.preview(payload(text="Проверка"))
    second=panel.preview(payload(text="Проверка"))
    assert not first["cached"] and second["cached"]
    assert first["audio"] == second["audio"]
    assert generated == ["Проверка"]
    assert (panel.root/"config.yaml").read_bytes() == before


def test_failed_preview_does_not_cache_partial(panel,monkeypatch):
    def fail(voice,speed,text,path):
        path.write_bytes(b"partial")
        raise RuntimeError("test failure")
    monkeypatch.setattr(panel,"_sapi",fail)
    with pytest.raises(RuntimeError):panel.preview(payload(text="Test"))
    assert not list(panel.temp.iterdir())


def test_failed_job_reports_failure(panel,monkeypatch):
    monkeypatch.setattr(panel,"preview",lambda _: (_ for _ in ()).throw(ValueError("bad sample")))
    job=panel.create_job("preview",payload())
    for _ in range(100):
        if panel.jobs[job]["status"]=="error":break
        time.sleep(.01)
    assert panel.jobs[job]=={"status":"error","error":"bad sample"}


@pytest.fixture
def endpoint(panel):
    server=create_server(panel,0)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}",panel
    server.shutdown();server.server_close();thread.join()


def test_http_isolation_and_profile(endpoint):
    base,panel=endpoint
    with urlopen(base) as response:
        assert panel.token in response.read().decode()
        assert response.headers["X-Frame-Options"]=="DENY"
    encoded=json.dumps(payload()).encode()
    bad=Request(base+"/api/profile",data=encoded,headers={"Content-Type":"application/json"})
    with pytest.raises(HTTPError) as error:urlopen(bad)
    assert error.value.code==403
    cross=Request(base+"/api/profile",data=encoded,headers={"X-Panel-Token":panel.token,"Origin":"https://example.com"})
    with pytest.raises(HTTPError) as error:urlopen(cross)
    assert error.value.code==403
    good=Request(base+"/api/profile",data=encoded,headers={"X-Panel-Token":panel.token,"Origin":base})
    with urlopen(good) as response:assert json.loads(response.read())["saved"]
    with pytest.raises(HTTPError) as error:urlopen(base+"/config.yaml")
    assert error.value.code==404


def test_invalid_host_rejected(endpoint):
    base,_=endpoint
    with pytest.raises(HTTPError) as error:urlopen(Request(base,headers={"Host":"malicious.example"}))
    assert error.value.code==403


def test_empty_text_rejected(panel):
    with pytest.raises(ValueError):panel.preview(payload(text=""))
    with pytest.raises(ValueError):panel.preview(payload(text="a"*401))
