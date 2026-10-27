#!/usr/bin/env bash
# FAS 一键启动（需先配置 data/llm_config.json）
cd "$(dirname "$0")"
exec python -X utf8 app.py
