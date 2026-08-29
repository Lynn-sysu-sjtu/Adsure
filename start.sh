#!/bin/bash
# 审心 · 一键启动所有服务
# 用法：./start.sh
# 停止：./stop.sh

cd "$(dirname "$0")"

PID_FILE=".pids"
mkdir -p logs

# 如果已经在跑，先停掉
if [ -f "$PID_FILE" ]; then
    echo "检测到已有进程，先停止..."
    while read pid; do
        kill "$pid" 2>/dev/null
    done < "$PID_FILE"
    rm -f "$PID_FILE"
    sleep 1
fi

echo "=============================="
echo " 审心 · 启动所有服务"
echo "=============================="

# 启动函数：崩溃后自动重启
_run() {
    local name="$1"
    local cmd="$2"
    while true; do
        echo "[$(date '+%H:%M:%S')] 启动 $name..."
        eval "$cmd"
        echo "[$(date '+%H:%M:%S')] $name 异常退出，3秒后重启..."
        sleep 3
    done
}

_run "bot_listener" "python3 bot_listener.py" >> logs/bot_listener.log 2>&1 &
echo $! >> "$PID_FILE"
echo "✓ bot_listener  已启动 (PID: $!)"

_run "worker" "python3 worker.py" >> logs/worker.log 2>&1 &
echo $! >> "$PID_FILE"
echo "✓ worker        已启动 (PID: $!)"

_run "app" "python3 app.py" >> logs/app.log 2>&1 &
echo $! >> "$PID_FILE"
echo "✓ 法务工作台    已启动 (PID: $!)"

echo ""
echo "所有服务在后台运行，日志在 logs/ 目录"
echo "法务工作台：http://localhost:5001"
echo "停止所有服务：./stop.sh"
echo "实时查看日志：tail -f logs/bot_listener.log"
