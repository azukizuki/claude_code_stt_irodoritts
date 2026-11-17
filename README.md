# claude_code_stt_irodoritts

Claude Code の応答が終わるたびに、その応答を [Irodori-TTS](https://github.com/Aratako/Irodori-TTS) で読み上げる Claude Code プラグイン（`irodori-tts-voice`）です。音声の合成と再生は手元の Mac だけで行い、外部とは通信しません。

## 動作環境
- macOS（再生に `afplay` を使います）。Apple Silicon を推奨します
- Claude Code（プラグイン機能が使えるバージョン）
- `python3`（hook の実行に使います。標準ライブラリだけで動きます）
- [uv](https://docs.astral.sh/uv/)（Irodori-TTS の環境構築に使います）

## 導入手順

### 1. Irodori-TTS を用意する
```sh
git clone https://github.com/Aratako/Irodori-TTS.git ~/Irodori-TTS
cd ~/Irodori-TTS
uv sync --extra cpu   # macOS は cpu を指定する（Apple GPU（MPS）も使われる）
```
モデル（Aratako/Irodori-TTS-v4.1-Small）は、読み上げサーバーを初めて起動したときに Hugging Face からダウンロードします。2 回目以降は手元のモデルだけを使います。

Irodori-TTS のコードとモデルは、このリポジトリには含まれていません。それぞれのライセンスに従って利用してください。

先に WebUI（`uv run python gradio_app.py`）で 1 回生成しておくと、ダウンロードと動作の確認を同時に済ませられます。

### 2. プラグインを入れる
Claude Code の中で次を実行します。
```
/plugin marketplace add <このリポジトリの URL またはローカルのパス>
/plugin install irodori-tts-voice@claude-code-irodoritts
```
ローカルに clone した場合は、パスを `~/claude_code_stt_irodoritts` のように指定できます。

インストールすると設定の入力画面が出るので、`Irodori-TTS のフォルダ` に手順 1 のフォルダ（例: `~/Irodori-TTS`）を指定します。

### 3. Claude Code を起動し直す
起動時に読み上げサーバーが自動で立ち上がります。モデルの読み込みに数十秒かかり、その間の応答は読み込みが終わってから読み上げます。

## 使い方
- 応答が終わるたびに、自動で読み上げます
- 読み上げ中に次の応答が終わると、前の読み上げを止めて新しい応答を読みます
- 表は「1 列目。見出しは、値。」の形で読みます。長いコードは「N 行のコードは省略します」とだけ読みます。見出しの前では少し間を空けます

### オン・オフ
| やりたいこと | 方法 |
|---|---|
| プラグインごと止める | `/plugin disable irodori-tts-voice@claude-code-irodoritts`（再開は `enable`） |
| そのセッションだけ止める | `IRODORI_TTS=0 claude` で起動する |
| 起動中のセッションで一時的に止める | `touch ~/.claude/plugins/data/<プラグインのID>/off`（消せば再開） |

### 設定の変更
`/plugin configure irodori-tts-voice@claude-code-irodoritts` で、次の値を変えられます。

| 項目 | 既定値 | 内容 |
|---|---|---|
| `irodori_dir` | なし（必須） | Irodori-TTS のフォルダ |
| `port` | 8765 | 読み上げサーバーのポート |
| `max_chars` | 5000 | 読み上げる最大文字数。0 で上限なし |

## 声のカスタマイズ
声の設定はプラグインのデータフォルダ（`~/.claude/plugins/data/<プラグインのID>/voice/`）にあります。読み上げのたびに読み込むので、変えてもサーバーの再起動は不要です。

| ファイル | 内容 |
|---|---|
| `caption.txt` | 声の説明文（例: 落ち着いた低めの女性の声で、ゆっくり話す） |
| `speed.txt` | 話す速さ。1.0 が標準で、小さいほど速い（初期値 0.85） |
| `seed.txt` | 乱数の固定値。変えると声質が変わる |
| `ref.wav` | 参照音声。置くとこの声に寄せて読む（初期状態ではなし） |

### 声を固定する
説明文だけだと、読み上げのたびに声が少し変わることがあります。気に入った声が出たら、その音声を `ref.wav` として保存すると声が安定します。
```sh
cp "$TMPDIR/irodori_speak_0.wav" ~/.claude/plugins/data/<プラグインのID>/voice/ref.wav
```
`irodori_speak_0.wav` は、直前の読み上げの最初の部分の音声です。

## トラブルシューティング
- 読み上げられないときは、`~/.claude/plugins/data/<プラグインのID>/server.log` を確認してください。`curl 127.0.0.1:8765/health` が `ready` を返せば、サーバーは動いています
- Irodori-TTS の venv が見つからないときは、`/plugin configure` で `irodori_dir` を確認してください。`<irodori_dir>/.venv/bin/python` が存在する必要があります
- サーバーを止めたいときは、`pkill -f irodori-tts-voice/scripts/server.py` を実行します。次に Claude Code を起動したときに、また自動で立ち上がります
- Irodori-TTS は日本語専用のモデルなので、英単語の読みがおかしくなることがあります

## 仕組み
- `SessionStart` hook（`scripts/ensure_server.py`）: 読み上げサーバーが止まっていれば、Irodori-TTS の venv で裏で起動します。Claude Code を閉じてもサーバーは動き続けます
- `Stop` hook（`scripts/speak.py`）: 最後の応答を読み上げ用に整えて、サーバーへ送ります
- 読み上げサーバー（`scripts/server.py`）: `127.0.0.1` だけで待ち受けます。文の切れ目で分けて合成し、1 つを再生している間に次を合成します

## 開発
マーケットプレイスを経由せずに試すときは、次のように起動します。
```sh
claude --plugin-dir ./plugins/irodori-tts-voice
```
