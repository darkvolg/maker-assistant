"""Isolated, loopback-only voice audition panel. Never writes assistant settings."""
import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import secrets
import tempfile
import threading
import time
import wave
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DEFAULT_TEXT = "Привет! Я помощник для мастерской. Резисторы десять килоом лежат в ячейке А двенадцать. Таймер установлен на пять минут."


class Panel:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.token = secrets.token_urlsafe(32)
        self.work = tempfile.TemporaryDirectory(prefix="maker-voice-panel-")
        self.temp = Path(self.work.name)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.jobs = {}
        self.lock = threading.Lock()
        self.voice_cache = {}
        self.audio = {}
        self.profile_path = self.root / "data" / "voice-panel" / "profile.yaml"

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.work.cleanup()

    def voices(self, engine, refresh=False):
        if engine not in ("sapi", "edge-tts"):
            raise ValueError("Неизвестный источник голосов")
        if refresh:
            self.voice_cache.pop(engine, None)
        if engine in self.voice_cache:
            return self.voice_cache[engine]
        if engine == "edge-tts":
            import edge_tts
            async def fetch():
                return await asyncio.wait_for(edge_tts.list_voices(), timeout=25)
            raw = asyncio.run(fetch())
            result = [dict(id=v["ShortName"], name=v["ShortName"].split("-")[-1].replace("Neural", ""),
                           locale=v["Locale"], gender=v.get("Gender", ""), engine=engine,
                           description=v.get("FriendlyName", v["ShortName"])) for v in raw]
        else:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            try:
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                result = []
                for voice in speaker.GetVoices():
                    description = voice.GetDescription()
                    language = voice.GetAttribute("Language").split(";")[0].lower()
                    locale = {"419":"ru-RU", "409":"en-US", "809":"en-GB"}.get(language, "other")
                    result.append(dict(id=voice.Id, name=description.split(" - ")[0].replace("Microsoft ", ""),
                                       locale=locale, gender=voice.GetAttribute("Gender"), engine=engine,
                                       description=description))
            finally:
                pythoncom.CoUninitialize()
        self.voice_cache[engine] = result
        return result

    def current(self):
        from assistant.config import load_config
        config = load_config(self.root / "config.yaml")
        tts = config.get("tts", {})
        result = {"engine":tts.get("engine", "sapi"), "voice":tts.get("sapi_voice") if tts.get("engine") == "sapi" else tts.get("voice"),
                  "threshold":config.get("audio", {}).get("energy_threshold", .015),
                  "input_device":config.get("audio", {}).get("input_device"), "text":DEFAULT_TEXT}
        if self.profile_path.exists():
            import yaml
            result["draft"] = yaml.safe_load(self.profile_path.read_text(encoding="utf-8"))
        return result

    def devices(self):
        import sounddevice as sd
        default = int(sd.default.device[0])
        devices = [dict(id=i, name=d["name"], host=sd.query_hostapis(d["hostapi"])["name"],
                        default=i == default) for i,d in enumerate(sd.query_devices()) if d["max_input_channels"]]
        return devices

    def validate_voice(self, payload):
        engine, voice_id = payload.get("engine"), payload.get("voice")
        voice = next((v for v in self.voices(engine) if v["id"] == voice_id), None)
        if not voice:
            raise ValueError("Выбранный голос недоступен")
        speed = payload.get("speed", 0)
        if type(speed) is not int or not -30 <= speed <= 30 or speed % 5:
            raise ValueError("Скорость: от −30 до +30 с шагом 5")
        return voice, speed

    def create_job(self, action, payload):
        if action not in ("preview", "microphone"):
            raise ValueError("Неизвестная операция")
        with self.lock:
            if sum(j["status"] in ("queued", "running") for j in self.jobs.values()) >= 3:
                raise ValueError("Уже выполняются запросы. Дождись завершения.")
            if len(self.jobs) >= 500:
                raise ValueError("Слишком много запросов за сеанс. Перезапусти панель.")
            job_id = secrets.token_hex(12)
            self.jobs[job_id] = {"status":"queued"}
        self.pool.submit(self._work, job_id, action, payload)
        return job_id

    def _work(self, job_id, action, payload):
        with self.lock:
            self.jobs[job_id] = {"status":"running"}
        try:
            result = self.preview(payload) if action == "preview" else self.microphone(payload)
            with self.lock:
                self.jobs[job_id] = {"status":"done", **result}
        except Exception as exc:
            message = "Сервис не ответил за отведённое время. Попробуй ещё раз." if isinstance(exc, TimeoutError) else str(exc)
            with self.lock:
                self.jobs[job_id] = {"status":"error", "error":message[:400]}

    def preview(self, payload):
        voice, speed = self.validate_voice(payload)
        text = payload.get("text", DEFAULT_TEXT)
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 400:
            raise ValueError("Тестовая фраза должна содержать от 1 до 400 символов")
        key = hashlib.sha256(json.dumps([voice["engine"],voice["id"],speed,text],ensure_ascii=False).encode()).hexdigest()
        suffix = ".wav" if voice["engine"] == "sapi" else ".mp3"
        path = self.temp / (key + suffix)
        start = time.monotonic()
        cached = path.exists()
        if not cached:
            partial = self.temp / (key + ".partial" + suffix)
            try:
                if voice["engine"] == "sapi":
                    self._sapi(voice["id"], speed, text, partial)
                else:
                    import edge_tts
                    async def generate():
                        await asyncio.wait_for(edge_tts.Communicate(text,voice["id"],rate=f"{speed:+d}%").save(str(partial)),timeout=30)
                    asyncio.run(generate())
                os.replace(partial, path)
            finally:
                if partial.exists():
                    partial.unlink()
        with self.lock:
            self.audio[key] = path
        return {"audio":"/audio/"+key, "seconds":round(time.monotonic()-start,2), "cached":cached, "voice":voice["name"]}

    @staticmethod
    def _sapi(voice_id, speed, text, path):
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Voice = next(v for v in speaker.GetVoices() if v.Id == voice_id)
            # SAPI uses a different rate scale; the UI labels the shared slider as relative speed.
            speaker.Rate = round(speed / 10)
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            stream.Format.Type = 22
            stream.Open(str(path), 3)
            try:
                speaker.AudioOutputStream = stream
                speaker.Speak(text, 16)
            finally:
                stream.Close()
        finally:
            pythoncom.CoUninitialize()

    def microphone(self, payload):
        import numpy as np
        import sounddevice as sd
        from assistant.utils.audio import resolve_input
        device = payload.get("device")
        if device is not None and type(device) is not int:
            raise ValueError("Неверный микрофон")
        mode = payload.get("mode", "speech")
        if mode not in ("speech", "noise"):
            raise ValueError("Неверный режим записи")
        device, info = resolve_input(device)
        rate = int(info["default_samplerate"])
        parts, errors = [], []
        def capture(data, frames, timing, status):
            parts.append(data[:,0].copy())
            if status.input_overflow:
                errors.append(True)
        with sd.InputStream(device=device, channels=1, samplerate=rate, dtype="float32", callback=capture):
            time.sleep(3 if mode == "noise" else 5)
        if not parts or errors:
            raise ValueError("Не удалось получить непрерывную запись. Проверь микрофон.")
        samples = np.concatenate(parts)
        rms = float(np.sqrt(np.mean(samples**2)))
        key = secrets.token_hex(32)
        path = self.temp/(key+".wav")
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate)
            wav.writeframes((np.clip(samples,-1,1)*32767).astype("<i2").tobytes())
        with self.lock:
            self.audio[key] = path
        result = {"audio":"/audio/"+key,"rms":round(rms,5),"peak":round(float(np.max(np.abs(samples))),4),
                  "device":info["name"], "mode":mode}
        if mode == "noise":
            result["suggested_threshold"] = round(min(.1,max(.002,rms*3)),4)
        return result

    def save_profile(self, payload):
        voice, speed = self.validate_voice(payload)
        threshold = payload.get("threshold", .015)
        if type(threshold) not in (int,float) or not math.isfinite(threshold) or not .001 <= threshold <= .2:
            raise ValueError("Порог должен быть от 0.001 до 0.2")
        device = payload.get("device")
        device_info = None
        if device is not None:
            if type(device) is not int:
                raise ValueError("Выбранный микрофон недоступен")
            device_info = next((d for d in self.devices() if d["id"] == device), None)
            if device_info is None:
                raise ValueError("Выбранный микрофон недоступен")
        import yaml
        profile = {"format":1,"purpose":"voice-panel-draft-only", "voice":{"engine":voice["engine"],"id":voice["id"],
                   "name":voice["name"],"speed":speed}, "audio":{"input_device":device,"energy_threshold":float(threshold)}}
        if device_info:
            profile["audio"].update(input_name=device_info["name"], input_host=device_info["host"])
        with self.lock:
            self.profile_path.parent.mkdir(parents=True,exist_ok=True)
            partial = self.profile_path.with_suffix(".tmp")
            partial.write_text(yaml.safe_dump(profile,allow_unicode=True,sort_keys=False),encoding="utf-8")
            os.replace(partial,self.profile_path)
        return {"saved":True,"path":"data/voice-panel/profile.yaml","message":"Пробный профиль сохранён. Рабочие настройки не изменены."}


class Handler(BaseHTTPRequestHandler):
    server_version = "MakerVoicePanel/1"

    def log_message(self, *args):
        pass

    def _allowed(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def _send(self, status, data, kind="application/json; charset=utf-8"):
        if isinstance(data,(dict,list)):
            data=json.dumps(data,ensure_ascii=False).encode("utf-8")
        elif isinstance(data,str):
            data=data.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",kind)
        self.send_header("Content-Length",str(len(data)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
            pass

    def do_GET(self):
        if not self._allowed():
            return self._send(403,{"error":"Открывай панель по адресу 127.0.0.1"})
        path=urlsplit(self.path).path
        panel=self.server.panel
        try:
            if path == "/":
                html=(panel.root/"assets/voice-panel.html").read_text(encoding="utf-8").replace("__PANEL_TOKEN__",panel.token)
                return self._send(200,html,"text/html; charset=utf-8")
            if path == "/api/current":return self._send(200,panel.current())
            if path == "/api/devices":return self._send(200,panel.devices())
            if path.startswith("/api/jobs/"):
                with panel.lock:job=panel.jobs.get(path.rsplit("/",1)[1])
                return self._send(200 if job else 404,job or {"error":"Запрос не найден"})
            if path.startswith("/audio/"):
                with panel.lock:audio=panel.audio.get(path.rsplit("/",1)[1])
                if audio and audio.exists():
                    return self._send(200,audio.read_bytes(),"audio/wav" if audio.suffix==".wav" else "audio/mpeg")
            return self._send(404,{"error":"Не найдено"})
        except Exception as exc:
            return self._send(500,{"error":str(exc)[:400]})

    def do_POST(self):
        origin=f"http://127.0.0.1:{self.server.server_port}"
        if not self._allowed() or self.headers.get("Origin",origin)!=origin or self.headers.get("X-Panel-Token")!=self.server.panel.token:
            return self._send(403,{"error":"Обнови страницу панели"})
        try:
            length=int(self.headers.get("Content-Length","0"))
            if not 0 < length <= 8192:
                raise ValueError("Неверный размер запроса")
            payload=json.loads(self.rfile.read(length))
            if not isinstance(payload,dict):raise ValueError("Ожидается объект")
            path=urlsplit(self.path).path
            panel=self.server.panel
            if path == "/api/voices":return self._send(200,panel.voices(payload.get("engine"), payload.get("refresh") is True))
            if path == "/api/preview":return self._send(202,{"job":panel.create_job("preview",payload)})
            if path == "/api/microphone":return self._send(202,{"job":panel.create_job("microphone",payload)})
            if path == "/api/profile":return self._send(200,panel.save_profile(payload))
            return self._send(404,{"error":"Не найдено"})
        except (ValueError,TypeError,KeyError) as exc:
            return self._send(400,{"error":str(exc)[:400]})
        except Exception as exc:
            return self._send(503,{"error":str(exc)[:400] or "Источник временно недоступен"})


def create_server(panel, port=8765):
    server=ThreadingHTTPServer(("127.0.0.1",port),Handler)
    server.panel=panel
    return server


def main():
    parser=argparse.ArgumentParser(description="Локальная панель сравнения голосов")
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--open",action="store_true")
    args=parser.parse_args()
    panel=Panel()
    try:
        server=create_server(panel,args.port)
    except OSError:
        panel.close()
        print("Порт занят. Закрой прежнюю панель или укажи --port 8766.")
        return 1
    url=f"http://127.0.0.1:{server.server_port}"
    print(f"Голоса и настройки: {url}\nCtrl+C — закрыть панель. Рабочие настройки не изменяются.",flush=True)
    if args.open:webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        panel.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
