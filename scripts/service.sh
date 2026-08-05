#!/usr/bin/env bash
# GeoLook 看板常驻服务（macOS LaunchAgent）
#
#   ./service.sh install     注册并启动：登录自启、崩溃自动拉起、不随终端/Claude 退出
#   ./service.sh uninstall   停止并移除
#   ./service.sh status      看运行状态
#   ./service.sh log         跟看服务日志
#
# 说明：服务只绑定 127.0.0.1:8765（插件与周期复跑都依赖这个固定端口）。
# 常驻的另一个收益：geo.json 里配置的「周期复跑」只在看板运行时触发，
# 服务常驻后到期就会自动跑完整一期，不再依赖你手动开着看板。

set -euo pipefail

LABEL="cc.geolook.dashboard"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/geolook-dashboard.log"
PY="$(command -v python3)"
UID_N="$(id -u)"

case "${1:-}" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$PY</string>
    <string>$ROOT/scripts/geo.py</string>
    <string>ui</string>
    <string>--no-open</string>
    <string>--port</string><string>8765</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
EOF
    # 先清掉可能占着端口的临时实例，让常驻服务接管
    launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null || true
    OLD=$(lsof -ti :8765 2>/dev/null || true)
    [ -n "$OLD" ] && kill $OLD 2>/dev/null && sleep 1
    launchctl bootstrap "gui/$UID_N" "$PLIST"
    sleep 2
    if curl -fsS -m 5 http://127.0.0.1:8765/api/projects >/dev/null 2>&1; then
      echo "✓ 已注册常驻服务：$LABEL"
      echo "  http://127.0.0.1:8765 · 登录自启 · 崩溃自动拉起 · 日志 $LOG"
      echo "  关闭 Claude / 终端都不影响；卸载：./service.sh uninstall"
    else
      echo "✗ 服务未响应，查看日志：tail -50 $LOG"; exit 1
    fi ;;

  uninstall)
    launchctl bootout "gui/$UID_N/$LABEL" 2>/dev/null && echo "✓ 已停止并移除" || echo "服务本就不在运行"
    rm -f "$PLIST" ;;

  status)
    if launchctl print "gui/$UID_N/$LABEL" >/dev/null 2>&1; then
      PID=$(launchctl print "gui/$UID_N/$LABEL" 2>/dev/null | awk '/pid =/{print $3}')
      echo "✓ 常驻服务运行中（pid ${PID:-?}）"
      curl -fsS -m 3 http://127.0.0.1:8765/api/projects >/dev/null 2>&1 \
        && echo "✓ 看板可访问：http://127.0.0.1:8765" || echo "✗ 端口无响应，看日志：$LOG"
    else
      echo "未安装。运行：./service.sh install"
    fi ;;

  log) tail -f "$LOG" ;;

  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
