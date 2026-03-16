#!/bin/bash
# 等第一輪跑完，然後自動跑第二輪
set -e
cd /Users/te-shuwang/ipas-quiz

export PYTHONIOENCODING=utf-8
export GEMINI_API_KEY=AIzaSyAZf6OuOXjiMkW8pITZIdl536psQ1PmPwg

echo "=== 等待第一輪完成 ==="
while pgrep -f "batch_generate.py" > /dev/null 2>&1; do
    DONE=$(python -c "import json; p=json.load(open('data/batch_progress.json')); print(len(p['completed']))" 2>/dev/null)
    echo "$(date '+%H:%M:%S') 第一輪進度: ${DONE}/234"
    sleep 120
done

echo ""
echo "=== 第一輪已完成，開始第二輪 ==="
echo ""

python -u batch_round2.py 2>&1 | tee data/batch_r2_log.txt

echo ""
echo "=== 全部完成 ==="
python -c "from database import get_stats; s=get_stats(); print(f'題庫總計: {s[\"total\"]} 題')"
