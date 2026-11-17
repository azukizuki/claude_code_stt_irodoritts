"""Irodori-TTS 常駐読み上げサーバー。POST /speak に本文テキストを送ると合成して afplay で再生する。

Irodori-TTS の venv の python で起動する（ensure_server.py が起動する）。
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# 取得済みのモデルだけを使い、Hugging Face へ通信しない
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

sys.path.insert(0, str(Path(__file__).parent))
from common import PAUSE, port, voice_dir  # noqa: E402

REPO = Path(os.path.expanduser(os.environ.get("IRODORI_DIR", "~/Irodori-TTS")))
sys.path.insert(0, str(REPO))
os.chdir(REPO)

from irodori_tts.inference_runtime import (  # noqa: E402
    RuntimeKey,
    SamplingRequest,
    default_runtime_device,
    download_hf_checkpoint,
    get_cached_runtime,
    list_available_runtime_precisions,
    save_wav,
)

PORT = port()
CHECKPOINT = os.environ.get("IRODORI_CHECKPOINT", "Aratako/Irodori-TTS-v4.1-Small")
STYLE_DIR = voice_dir()
OUT_DIR = Path(os.environ.get("TMPDIR", "/tmp"))
CHUNK = 80  # 1 回の合成の目安文字数（文の切れ目で分ける）
CHUNK_HARD = 120  # 区切りが見つからないときの上限（max_seconds 30 秒に収める）


def read_style() -> tuple[str | None, str | None]:
    """caption.txt（声の説明）と ref.wav（参照音声）をリクエストごとに読む。再起動不要。"""
    cap = STYLE_DIR / "caption.txt"
    caption = cap.read_text().strip() if cap.exists() else ""
    ref = STYLE_DIR / "ref.wav"
    return (caption or os.environ.get("IRODORI_CAPTION") or None, str(ref) if ref.exists() else None)


def read_speed() -> float:
    """speed.txt の値を duration_scale として使う（1.0 が標準、小さいほど速い）。"""
    try:
        return float((STYLE_DIR / "speed.txt").read_text().strip())
    except (OSError, ValueError):
        return 1.0


def read_seed() -> int:
    """seed.txt の値で乱数を固定し、毎回同じ声質に寄せる。"""
    try:
        return int((STYLE_DIR / "seed.txt").read_text().strip())
    except (OSError, ValueError):
        return 42


SPLIT_LEVELS = [r"(?<=[、，,])", r"(?<=[：:；;）)」』])", r"(?<=\s)"]  # 優先度順の区切り


def _split_long(sent: str, level: int = 0) -> list[str]:
    """CHUNK_HARD を超える 1 文を、読点、括弧、空白の順に区切りを探して分ける。"""
    if len(sent) <= CHUNK_HARD:
        return [sent]
    if level >= len(SPLIT_LEVELS):  # 区切りがなければ最後の手段で切る
        return [sent[i : i + CHUNK_HARD] for i in range(0, len(sent), CHUNK_HARD)]
    pieces, cur = [], ""
    for part in re.split(SPLIT_LEVELS[level], sent):
        if cur and len(cur) + len(part) > CHUNK:
            pieces.append(cur)
            cur = ""
        cur += part
    if cur:
        pieces.append(cur)
    return [q for piece in pieces for q in _split_long(piece, level + 1)]


PAUSE_SECONDS = 0.6


def split_with_pause(text: str) -> list[tuple[str, bool]]:
    """目印で段落に分け、(チャンク, 直前に間を空けるか) の一覧にする。"""
    result = []
    for n, seg in enumerate(text.split(PAUSE)):
        for k, chunk in enumerate(split_text(seg)):
            result.append((chunk, n > 0 and k == 0))
    return result


def split_text(text: str) -> list[str]:
    """文の切れ目で分け、短い文は CHUNK までまとめる。"""
    chunks, cur = [], ""
    for sent in re.split(r"(?<=[。！？!?])", text):
        if not sent.strip():
            continue
        if len(sent) > CHUNK_HARD:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.extend(_split_long(sent))
            continue
        if cur and len(cur) + len(sent) > CHUNK:
            chunks.append(cur)
            cur = ""
        cur += sent
    if cur.strip():
        chunks.append(cur)
    return chunks


def load_runtime():
    device = default_runtime_device()
    precision = list_available_runtime_precisions(device)[0]
    ckpt = CHECKPOINT if CHECKPOINT.endswith((".pt", ".safetensors")) else download_hf_checkpoint(CHECKPOINT)
    key = RuntimeKey(
        checkpoint=ckpt,
        model_device=device,
        model_precision=precision,
        codec_device=device,
        codec_precision=precision,
        compile_model=False,
        compile_dynamic=False,
    )
    runtime, _ = get_cached_runtime(key)
    print(f"[irodori] ready device={device} precision={precision} port={PORT}", flush=True)
    return runtime


ready = threading.Event()
jobs: queue.Queue[str] = queue.Queue()
player: subprocess.Popen | None = None
lock = threading.Lock()


def stop_player() -> None:
    global player
    with lock:
        if player and player.poll() is None:
            player.terminate()
        player = None


def worker() -> None:
    global player
    runtime = load_runtime()
    ready.set()
    while True:
        text = jobs.get()
        while not jobs.empty():  # 溜まっている場合は最新だけ読む
            text = jobs.get()
        stop_player()
        caption, ref = read_style()
        for i, (chunk, pause) in enumerate(split_with_pause(text)):
            if not jobs.empty():  # 新しい依頼が来たら中断
                break
            try:
                req = SamplingRequest(
                    text=chunk, caption=caption, ref_wav=ref, no_ref=ref is None, duration_scale=read_speed(), seed=read_seed()
                )
                result = runtime.synthesize(req)
                out = OUT_DIR / f"irodori_speak_{i % 2}.wav"
                save_wav(out, result.audio, result.sample_rate)
            except Exception as e:  # noqa: BLE001
                print(f"[irodori] error: {e}", flush=True)
                break
            with lock:  # 前のチャンクの再生終了を待つ（次の合成は再生中に進む）
                prev = player
            if prev:
                prev.wait()
            if pause:
                time.sleep(PAUSE_SECONDS)
            if not jobs.empty():
                break
            with lock:
                player = subprocess.Popen(["afplay", str(out)])


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()
        self.wfile.write(b"ready" if ready.is_set() else b"loading")

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
        if self.path == "/speak" and body.strip():
            jobs.put(body.strip())
        elif self.path == "/stop":
            stop_player()
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args) -> None:
        pass


# 先にポートを確保する。二重起動したほうはここで失敗して終わる
try:
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
except OSError:
    print(f"[irodori] port {PORT} は使用中のため終了します（起動済みの可能性）", flush=True)
    sys.exit(0)
threading.Thread(target=worker, daemon=True).start()
httpd.serve_forever()
