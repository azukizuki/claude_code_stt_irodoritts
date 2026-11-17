---
description: Irodori-TTS の読み上げをすぐに止める（再生中の文と、まだ読んでいない残りを捨てる）
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/stop.py *)
---
!`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/stop.py ${CLAUDE_PLUGIN_DATA} ${user_config.port}`

上の 1 行をそのまま返してください。ほかには何も書かず、ツールも使わないでください。
