# SPICA Makefile
PY   := .venv/bin/python
PIP  := .venv/bin/pip
export PIP_INDEX_URL := https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_CACHE_DIR := $(CURDIR)/.cache/pip

.PHONY: deps venv deps-dsh up up-fg stop log status killall check test models tts-smoke package

venv:
	python3.12 -m venv .venv
	cp pip.conf .venv/pip.conf
	mkdir -p .cache/pip models workspace archives run assets/voices

deps: venv
	$(PIP) install -r requirements.txt
	@if [ ! -d runtime/dsh/node_modules/@deepseek-ai/dsh ]; then \
		echo "⚠ DSH 运行时未捆绑，正在安装（可选，跳过则用系统 DSH）..."; \
		$(MAKE) deps-dsh; \
	fi

deps-dsh:
	@mkdir -p runtime/dsh
	@cd runtime/dsh && npm install @deepseek-ai/dsh \
		--registry=https://registry.npmmirror.com \
		--cache ../../.cache/npm --no-audit --no-fund
	@echo "DSH runtime bundled → runtime/dsh/"

# 启动本地服务（后台守护：日志 run/server.log，pid run/server.pid）
up:
	@mkdir -p run
	@if [ -f run/server.pid ] && kill -0 $$(cat run/server.pid) 2>/dev/null; then \
		echo "已在运行 pid=$$(cat run/server.pid)，make log 看日志 / make stop 停止"; exit 0; fi
	@: > run/server.log
	@nohup $(PY) -m server.main >> run/server.log 2>&1 & \
	echo $$! > run/server.pid; \
	sleep 6; \
	if curl -s -m 3 -o /dev/null http://127.0.0.1:8666/ \
	   && ! grep -q "address already in use" run/server.log; then \
		echo "SPICA 已启动 → http://127.0.0.1:8666 （make log 跟日志）"; \
	else \
		echo "⚠ 启动失败：端口 8666 可能被旧进程占用。"; \
		echo "  请在你的终端运行: pkill -f server.main && make up"; 		rm -f run/server.pid; fi

# 前台运行（调试用，Ctrl+C 退出并清理子进程）
up-fg:
	$(PY) -m server.main

stop:
	@fuser -k 8666/tcp 2>/dev/null && echo stopped || echo not-running
	@rm -f run/server.pid

log:
	tail -f run/server.log | grep -vE "telemetry"

status:
	@fuser 8666/tcp 2>/dev/null && echo "运行中（端口 8666）" || echo "未运行（make up 启动）"

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


# ===== 打包 =====
package:
	@echo "检测平台..."
	@if [ "$(uname)" = "Darwin" ]; then \
		echo "▸ macOS: 构建 .app + .dmg"; \
		bash packaging/macos/build-dmg.sh; \
	elif [ "$(uname)" = "Linux" ]; then \
		echo "▸ Linux: 构建 AppImage"; \
		bash packaging/linux/build-appimage.sh; \
	else \
		echo "▸ Windows: 请运行 packaging/windows/build.bat"; \
	fi
