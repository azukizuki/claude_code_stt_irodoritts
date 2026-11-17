"""SessionStart hook。読み上げサーバーが止まっていれば裏で起動する（何度呼んでもよい）。"""
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import data_dir, port, voice_dir  # noqa: E402


def log(msg: str) -> None:
    print(f"[irodori-tts-voice] {msg}", file=sys.stderr)


def is_running() -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port()}/health", timeout=1)
        return True
    except Exception:
        return False


def main() -> None:
    # 声の設定がなければ初期値を置く（利用者が編集したものは上書きしない）
    voice_dir().mkdir(parents=True, exist_ok=True)
    for src in (Path(__file__).parent.parent / "voice-defaults").iterdir():
        dst = voice_dir() / src.name
        if not dst.exists():
            shutil.copy(src, dst)

    if is_running():
        return

    irodori = Path(os.path.expanduser(os.environ.get("CLAUDE_PLUGIN_OPTION_IRODORI_DIR", "")))
    python = irodori / ".venv" / "bin" / "python"
    if not python.exists():
        log(f"Irodori-TTS の venv が見つかりません: {python}（/plugin configure で irodori_dir を確認してください）")
        return

    env = {**os.environ, "IRODORI_DIR": str(irodori), "IRODORI_PORT": str(port()), "IRODORI_DATA_DIR": str(data_dir())}
    with open(data_dir() / "server.log", "ab") as out:
        subprocess.Popen(
            [str(python), str(Path(__file__).parent / "server.py")],
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # Claude Code を閉じてもサーバーは残す
        )


if __name__ == "__main__":
    main()
