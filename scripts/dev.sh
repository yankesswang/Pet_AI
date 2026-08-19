#!/usr/bin/env bash
#
# 一個指令把 Demo 跑起來：後端（2222）+ 前端（5173）。
#
# 為什麼需要這支：前端的「我要提問」與「文件庫」兩頁**沒有 mock 備援**
# （顯示假資料會讓所有核對結論失效）。所以後端沒開時，那兩頁只會顯示
# 「連不上後端」，看起來就像前端壞了。這支腳本確保兩個都起來、
# 而且在後端真的回應之後才告訴你可以開了。
#
# 用法：
#   ./scripts/dev.sh          # 前後端都起
#   ./scripts/dev.sh backend  # 只起後端
#
# Ctrl-C 會一起關掉。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv/bin/python"
BACKEND_PORT=2222
FRONTEND_PORT=5173
ONLY="${1:-all}"

if [[ ! -x "$VENV" ]]; then
  echo "找不到虛擬環境：$VENV" >&2
  echo "請先建立：python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt" >&2
  exit 1
fi

pids=()
cleanup() {
  trap - INT TERM EXIT
  for pid in "${pids[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo
  echo "已停止。"
}
trap cleanup INT TERM EXIT

port_busy() { lsof -ti "tcp:$1" -sTCP:LISTEN >/dev/null 2>&1; }

# ---- 後端 ----------------------------------------------------------------
if port_busy "$BACKEND_PORT"; then
  echo "· 後端 $BACKEND_PORT 已在執行，沿用既有的。"
else
  echo "· 啟動後端 http://127.0.0.1:$BACKEND_PORT"
  (cd "$ROOT/backend" && exec "$VENV" -m uvicorn app.main:app --reload --port "$BACKEND_PORT") &
  pids+=($!)
fi

# 等後端真的能回應才繼續 —— 前端太早開會先看到一次連線失敗
for _ in $(seq 1 40); do
  if curl -sf --max-time 1 "http://127.0.0.1:$BACKEND_PORT/api/health" -o /dev/null; then
    break
  fi
  sleep 0.5
done
if ! curl -sf --max-time 2 "http://127.0.0.1:$BACKEND_PORT/api/health" -o /dev/null; then
  echo "後端在 20 秒內沒有回應，請看上面的錯誤訊息。" >&2
  exit 1
fi
echo "  後端就緒（$(curl -s "http://127.0.0.1:$BACKEND_PORT/api/health" | tr ',' '\n' | grep rules_bundle_version | cut -d'"' -f4)）"

if [[ "$ONLY" == "backend" ]]; then
  echo
  echo "  API 文件： http://127.0.0.1:$BACKEND_PORT/docs"
  wait
fi

# ---- 前端 ----------------------------------------------------------------
if port_busy "$FRONTEND_PORT"; then
  echo "· 前端 $FRONTEND_PORT 已在執行，沿用既有的。"
else
  if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
    echo "· 安裝前端相依（首次執行）"
    (cd "$ROOT/frontend" && npm install)
  fi
  echo "· 啟動前端 http://127.0.0.1:$FRONTEND_PORT"
  (cd "$ROOT/frontend" && exec npx vite --port "$FRONTEND_PORT") &
  pids+=($!)
fi

for _ in $(seq 1 40); do
  curl -sf --max-time 1 "http://127.0.0.1:$FRONTEND_PORT/" -o /dev/null && break
  sleep 0.5
done

cat <<EOF

  ────────────────────────────────────────────────
   前端    http://127.0.0.1:$FRONTEND_PORT/#live
   文件庫  http://127.0.0.1:$FRONTEND_PORT/#library
   API 文件 http://127.0.0.1:$BACKEND_PORT/docs
  ────────────────────────────────────────────────
   Ctrl-C 一起停止

EOF

wait
