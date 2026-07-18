#!/bin/bash
# 审心本地开发启动脚本
# 用法：bash start_local.sh
# 会自动清理旧进程，启动 app / worker / bot_listener

cd "$(dirname "$0")"

echo "== 清理旧进程 =="
for name in "app.py" "worker.py" "bot_listener.py"; do
    pids=$(pgrep -f "$name" 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "  杀掉 $name (pid=$pids)"
        kill $pids 2>/dev/null
    fi
done
sleep 1

echo "== 启动服务 =="
python3 -u app.py          > /tmp/adsure_app.log          2>&1 & echo $! > /tmp/adsure_app.pid
python3 -u worker.py       > /tmp/adsure_worker.log       2>&1 & echo $! > /tmp/adsure_worker.pid
python3 -u bot_listener.py > /tmp/adsure_bot_listener.log 2>&1 & echo $! > /tmp/adsure_bot_listener.pid

sleep 2
echo ""
echo "== 进程状态 =="
for name in "app.py" "worker.py" "bot_listener.py"; do
    pid=$(pgrep -f "$name" | head -1)
    if [ -n "$pid" ]; then
        echo "  ✓ $name (pid=$pid)"
    else
        echo "  ✗ $name 启动失败"
    fi
done

echo ""
echo "日志位置："
echo "  app:          tail -f /tmp/adsure_app.log"
echo "  worker:       tail -f /tmp/adsure_worker.log"
echo "  bot_listener: tail -f /tmp/adsure_bot_listener.log"
echo ""
echo "本地工作台: http://localhost:5001"
