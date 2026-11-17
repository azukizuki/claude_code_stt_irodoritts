"""英単語をカタカナに置き換える（オプション）。server.py の worker から呼ぶ。標準ライブラリだけで書く。

引く順番: ユーザー辞書（voice/kana_dict.txt）→ キャッシュ（kana_cache.json）→ ローカル LLM。
LLM は OpenAI 互換の API（Ollama、LM Studio、mlx-lm など）で呼ぶ。失敗したら元の表記のまま残す。
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

from common import data_dir, voice_dir

TIMEOUT = 4.0  # LLM を待つ合計秒数。超えたら残りの語は英語のまま読む
BATCH = 25  # 1 回のリクエストで送る語数の上限

# 英字を含むまとまりを 1 語とする（v4.1、MP3、gpt-4o、max_chars、C++ など）
WORD = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*(?:[.'’\-_+][A-Za-z0-9]+)*(?:\+\+)?")
KATAKANA = re.compile(r"[゠-ヿ\s]+")  # カタカナ、長音、中黒、空白

SYSTEM_PROMPT = """あなたは、日本語の読み上げ用に英語の表記をカタカナの読みに変換する辞書です。
入力は英単語や略語の JSON 配列です。各要素をキー、そのカタカナの読みを値にした JSON オブジェクトだけを出力してください。
- IT やソフトウェアの分野で日本人が一般的に使う読みにする（例: GitHub→ギットハブ、README→リードミー、JSON→ジェイソン、macOS→マックオーエス）
- 1 文字ずつ読む略語はアルファベット読みにする（例: API→エーピーアイ、PR→ピーアール、MPS→エムピーエス）
- 単語として読む略語はそのまま読む（例: NASA→ナサ）
- 数字は日本語の読みをカタカナで書く（例: v4.1→ブイヨンテンイチ、MP3→エムピースリー）
- 値はカタカナと長音記号「ー」だけで書く。説明や前置きは書かない"""

_cache: dict[str, str] | None = None


def _cache_path():
    return data_dir() / "kana_cache.json"


def _load_cache() -> dict[str, str]:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_cache_path().read_text())
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save_cache() -> None:
    path = _cache_path()
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(_load_cache(), ensure_ascii=False, indent=0, sort_keys=True))
        tmp.replace(path)
    except OSError:
        pass


def load_user_dict() -> tuple[dict[str, str], dict[str, str]]:
    """kana_dict.txt を読む。読み上げのたびに呼ぶので、書き換えたら次から反映される。"""
    exact, lower = {}, {}
    try:
        lines = (voice_dir() / "kana_dict.txt").read_text().splitlines()
    except OSError:
        return exact, lower
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        word, kana = (s.strip() for s in line.split("=", 1))
        if word and kana:
            exact[word] = kana
            lower.setdefault(word.lower(), kana)
    return exact, lower


def _parse_json_object(content: str) -> dict:
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        obj = json.loads(content[start : end + 1])
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _post_chat(url: str, body: dict, timeout: float) -> str:
    req = urllib.request.Request(
        url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.load(res)["choices"][0]["message"].get("content") or ""


def ask_llm(words: list[str], url: str, model: str, timeout: float) -> dict[str, str]:
    """words のカタカナ読みを LLM に聞く。カタカナだけでできた答えだけを返す。"""
    body = {
        "model": model,
        "temperature": 0,
        # 思考モードのあるモデル（Qwen 3 以降など）は、思考を切らないと答えが間に合わない。
        # JSON を強制する response_format は、モデルによっては使えない（Ollama の qwen3.5 など）ので使わず、
        # プロンプトで JSON を指示して、返ってきた文から取り出す
        "reasoning_effort": "none",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(words, ensure_ascii=False)},
        ],
    }
    started = time.monotonic()
    try:
        content = _post_chat(url, body, timeout)
    except urllib.error.HTTPError as e:
        if e.code not in (400, 422):
            raise
        # reasoning_effort を受け付けないサーバー向けに、外して 1 回だけやり直す
        del body["reasoning_effort"]
        content = _post_chat(url, body, max(0.1, timeout - (time.monotonic() - started)))
    answer = _parse_json_object(content)
    # 小さいモデルはキーと値を逆にして返すことがある（{"ギットハブ": "GitHub"}）ので、逆向きも受け取る
    reverse = {v: k for k, v in answer.items() if isinstance(k, str) and isinstance(v, str)}
    result = {}
    for word in words:
        kana = answer.get(word) or reverse.get(word)
        if isinstance(kana, str) and KATAKANA.fullmatch(kana.strip()):
            result[word] = kana.strip()
    return result


def to_kana(text: str, url: str, model: str) -> str:
    """text の中の英単語をカタカナに置き換える。読みが分からない語は英語のまま残す。"""
    words = list(dict.fromkeys(m.group(0) for m in WORD.finditer(text)))
    if not words:
        return text
    exact, lower = load_user_dict()
    cache = _load_cache()
    reading: dict[str, str] = {}
    unknown = []
    for w in words:
        kana = exact.get(w) or lower.get(w.lower()) or cache.get(w)
        if kana:
            reading[w] = kana
        else:
            unknown.append(w)

    started = time.monotonic()
    learned: dict[str, str] = {}
    error = ""
    for i in range(0, len(unknown), BATCH):
        remaining = TIMEOUT - (time.monotonic() - started)
        if remaining <= 0.2:
            error = "タイムアウト"
            break
        try:
            learned.update(ask_llm(unknown[i : i + BATCH], url, model, remaining))
        except Exception as e:  # noqa: BLE001 接続できない、タイムアウト、応答が不正など
            error = f"{type(e).__name__}: {e}"
            break
    if learned:
        cache.update(learned)
        _save_cache()
    reading.update(learned)

    if unknown:
        left = [w for w in unknown if w not in learned]
        msg = f"[kana] LLM {len(learned)}/{len(unknown)} 語 {time.monotonic() - started:.2f}s"
        if learned:
            msg += " " + ", ".join(f"{w}→{k}" for w, k in learned.items())
        if left:
            msg += f" / 英語のまま: {', '.join(left)}"
        if error:
            msg += f" / {error}"
        print(msg, flush=True)

    return WORD.sub(lambda m: reading.get(m.group(0), m.group(0)), text)
