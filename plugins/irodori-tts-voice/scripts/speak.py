"""Claude Code Stop hook。最後の応答を整形して Irodori サーバーへ送る。"""
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import PAUSE, SKIP_NEXT, SKIP_NEXT_TTL, data_dir, port  # noqa: E402

# IRODORI_TTS=0 / off / false で無効（未設定なら有効）
if os.environ.get("IRODORI_TTS", "1").strip().lower() in ("0", "off", "false", "no"):
    sys.exit(0)
if (data_dir() / "off").exists():  # 起動中のセッションで一時的に止める
    sys.exit(0)

# /irodori-tts-voice:stop への返事は読み上げない（目印は一度使ったら消す）
skip = data_dir() / SKIP_NEXT
try:
    stamp = float(skip.read_text().strip() or 0)
    skip.unlink()
    if time.time() - stamp < SKIP_NEXT_TTL:
        sys.exit(0)
except (OSError, ValueError):
    pass

data = json.load(sys.stdin)
text = data.get("last_assistant_message") or ""
if not text and data.get("transcript_path"):
    for line in reversed(Path(data["transcript_path"]).read_text().splitlines()):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "assistant":
            parts = [c.get("text", "") for c in e["message"].get("content", []) if c.get("type") == "text"]
            if any(parts):
                text = "\n".join(parts)
                break

def table_to_speech(block: str) -> str:
    """表を「1 列目。見出しは、値。」の形で行ごとに読む。"""
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in block.strip().splitlines()]
    rows = [r for r in rows if not all(re.fullmatch(r":?-+:?", c) for c in r if c)]  # 区切り行
    if len(rows) < 2:
        return "\n".join("、".join(r) for r in rows) + "\n"
    header, lines = rows[0], []
    for r in rows[1:]:
        parts = [r[0]] if r and r[0] else []
        parts += [f"{h}は、{c}" if h else c for h, c in zip(header[1:], r[1:]) if c]
        lines.append("。".join(parts) + "。")
    return "\n".join(lines) + "\n"


def code_to_speech(m: re.Match) -> str:
    """1 行で短いコードは読み、それ以外は行数だけ伝える。"""
    body = m.group(1).strip()
    lines = [l for l in body.splitlines() if l.strip()]
    if len(lines) <= 1 and len(body) <= 40:
        return "\n" + body + "\n"
    return f"\n{len(lines)} 行のコードは省略します。\n"


text = re.sub(r"```[^\n]*\n(.*?)```", code_to_speech, text, flags=re.S)
text = re.sub(r"^#+\s*(.+)$", lambda m: f"{PAUSE}{m.group(1)}。", text, flags=re.M)  # 見出しの前で間を空ける
text = re.sub(r"(?:^\|.*\|[ \t]*(?:\n|$))+", lambda m: table_to_speech(m.group(0)), text, flags=re.M)
text = re.sub(r"https?://\S+", "", text)                   # URL
text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)       # リンク
text = re.sub(r"[`*#>]", "", text)                         # _ はパスや識別子に残す
text = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", text, flags=re.M)  # 箇条書き記号
text = re.sub(r"\s*\n\s*", "。", text.strip())
text = re.sub(r"[。、]{2,}", "。", text)
text = re.sub(rf"[。、]*{PAUSE}[。、]*", PAUSE, text).strip(PAUSE)

limit = int(float(os.environ.get("CLAUDE_PLUGIN_OPTION_MAX_CHARS") or os.environ.get("IRODORI_MAX_CHARS") or 5000))  # 0 で上限なし
if limit > 0 and len(text) > limit:
    cut = text.rfind("。", 0, limit)
    text = text[: cut + 1 if cut > 0 else limit]
if not text.strip():
    sys.exit(0)

# 英単語をカタカナに置き換える LLM（オプション）。URL とモデル名の両方があるときだけサーバーに伝える
headers = {}
kana_url = (os.environ.get("CLAUDE_PLUGIN_OPTION_KANA_LLM_URL") or "").strip()
kana_model = (os.environ.get("CLAUDE_PLUGIN_OPTION_KANA_LLM_MODEL") or "").strip()
if kana_url and kana_model:
    headers = {"X-Kana-Url": kana_url, "X-Kana-Model": kana_model}

try:
    urllib.request.urlopen(
        urllib.request.Request(f"http://127.0.0.1:{port()}/speak", data=text.encode("utf-8"), headers=headers),
        timeout=2,
    )
except Exception:
    pass  # サーバー未起動なら何もしない
