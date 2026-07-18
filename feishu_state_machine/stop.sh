#!/bin/bash
# 审心 · 停止所有服务

cd "$(dirname "$0")"

PID_FILE=".pids"

if [ -f "$PID_FILE" ]; then
    echo "正在停止已记录的进程..."
    while read pid; do
        if kill "$pid" 2>/dev/null; then
            echo "✓ 已停止进程 $pid"
        fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
fi

# 兜底：强杀所有残留的三个服务进程（匹配大小写 python/Python，兼容完整路径）
pkill -f "app\.py" 2>/dev/null
pkill -f "bot_listener\.py" 2>/dev/null
pkill -f "worker\.py" 2>/dev/null

echo "所有服务已停止"
