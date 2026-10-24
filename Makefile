# SPICA Makefile
PY   := .venv/bin/python
PIP  := .venv/bin/pip
export PIP_INDEX_URL := https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_CACHE_DIR := $(CURDIR)/.cache/pip

.PHONY: deps venv up down killall check test models tts-smoke

venv:
	python3.12 -m venv .venv
	cp pip.conf .venv/pip.conf
	mkdir -p .cache/pip models workspace archives run assets/voices

deps: venv
	$(PIP) install -r requirements.txt

# 启动本地服务（默认 127.0.0.1:8666）
up:
	$(PY) -m server.main

# 关停：按进程注册表清扫 + 兜底 pkill
killall:
	$(PY) -m server.lifecycle --killall

# 硬件/环境自检（服务端视角）
check:
	$(PY) -m server.check

test:
	$(PY) -m pytest tests -q

# 下载四个 sherpa-onnx 模型到 models/
models:
	$(PY) -m tools.download_models

# TTS 冒烟：合成一句到 assets/voices/_smoke.wav
tts-smoke:
	$(PY) -m server.tts.smoke
