"""hook とサーバーで共有する設定の読み出し。"""
import os
from pathlib import Path

PAUSE = "⏸"  # speak.py が見出しの前に入れ、server.py が間を空ける目印


def port() -> int:
    return int(float(os.environ.get("CLAUDE_PLUGIN_OPTION_PORT") or os.environ.get("IRODORI_PORT") or 8765))


def data_dir() -> Path:
    """プラグイン更新を跨いで残る置き場所。プラグイン外で動かすときは ~/.irodori-tts-voice。"""
    d = os.environ.get("CLAUDE_PLUGIN_DATA") or os.environ.get("IRODORI_DATA_DIR")
    return Path(d) if d else Path.home() / ".irodori-tts-voice"


def voice_dir() -> Path:
    return data_dir() / "voice"
