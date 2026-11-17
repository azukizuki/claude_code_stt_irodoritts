"""/irodori-tts-voice:stop から呼ぶ。再生中の読み上げと、まだ読んでいない残りを止める。

使い方: stop.py <データフォルダ> <ポート>（skill の本文で ${CLAUDE_PLUGIN_DATA} と ${user_config.port} を渡す）
"""
import os
import sys
import time
import urllib.request
from pathlib import Path

if len(sys.argv) > 1 and sys.argv[1]:
    os.environ["IRODORI_DATA_DIR"] = sys.argv[1]
if len(sys.argv) > 2 and sys.argv[2]:
    os.environ["IRODORI_PORT"] = sys.argv[2]

sys.path.insert(0, str(Path(__file__).parent))
from common import SKIP_NEXT, data_dir, port  # noqa: E402

# このコマンドへの Claude の返事は読み上げない（speak.py が一度だけ見て消す）
try:
    data_dir().mkdir(parents=True, exist_ok=True)
    (data_dir() / SKIP_NEXT).write_text(str(time.time()))
except OSError:
    pass

try:
    urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port()}/stop", data=b""), timeout=2)
    print("読み上げを停止しました。")
except Exception:
    print("読み上げサーバーに接続できませんでした（起動していない可能性があります）。")
