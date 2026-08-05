#!/usr/bin/env bash
# GeoLook 采样沙箱：与日常浏览完全隔离的 Chrome 环境，扩展常驻。
#
#   ./sandbox.sh --init      首次：创建沙箱并手动装一次扩展（只做这一次）
#   ./sandbox.sh             一次性沙箱：从模板复制并清空站点数据，用完即弃
#   ./sandbox.sh --keep      持久沙箱：登录态保留，必须登录的引擎用这个
#   ./sandbox.sh --keep https://www.doubao.com/chat/     直接打开某引擎
#   ./sandbox.sh --check     自检：模板、扩展、看板是否都就位
#   ./sandbox.sh --reset     删掉模板重来
#
# 为什么不是无痕：无痕默认禁用扩展、关窗清空存储（未上传的样本会丢），
# 而国内引擎多数必须登录，无痕并不能让它变干净。沙箱两个问题都没有。
#
# 为什么要 --init 手动装一次：Chrome 137 起已移除 --load-extension 命令行开关，
# 无法再用命令行自动装未打包扩展。装一次进模板，之后每次沙箱都自带它。
#
# 沙箱解决的是「浏览器层面干净」——没有你的历史、Cookie、自查行为画像。
# 它变不出账号：必须登录的引擎在持久沙箱里登一次长期复用（不用每周新建）。
# 也不改变各家服务条款——自动跑队列的风险边界见 README。

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="${GEOLOOK_SANDBOX_DIR:-$HOME/.geolook-sandbox}"
MODE=once; URL=""

for arg in "$@"; do
  case "$arg" in
    --init) MODE=init ;;
    --keep) MODE=keep ;;
    --reset) MODE=reset ;;
    --check) MODE=check ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    http*) URL="$arg" ;;
    *) echo "未知参数：$arg（--help 看用法）" >&2; exit 1 ;;
  esac
done

# 优先用 Chrome for Testing（playwright/puppeteer 装的）：它保留了 --load-extension，
# 扩展可以随启动自动装载，完全不需要 --init 手动装一次。
# 日常 Chrome 137 起移除了该开关，只能走「模板 Profile + 手动装一次」的兜底路径。
CFT=""
for p in "$HOME/Library/Caches/ms-playwright"/chromium-*/chrome-mac*/"Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing" \
         "$HOME/.cache/puppeteer/chrome"/*/chrome-mac*/"Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"; do
  [ -x "$p" ] && CFT="$p"    # glob 升序，循环结束时留下的是最新版本
done

CHROME=""
for p in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/Applications/Chromium.app/Contents/MacOS/Chromium" \
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
  "$(command -v google-chrome || true)" \
  "$(command -v chromium || true)"; do
  [ -n "$p" ] && [ -x "$p" ] && CHROME="$p" && break
done
[ -z "$CFT" ] && [ -z "$CHROME" ] && { echo "没找到 Chrome/Chromium，请先安装" >&2; exit 1; }

launch() {  # $1=profile 目录  $2=起始 URL
  if [ -n "$CFT" ]; then
    "$CFT" --user-data-dir="$1" --no-first-run --no-default-browser-check \
      --disable-sync --disable-background-networking \
      --load-extension="$DIR" --disable-extensions-except="$DIR" \
      ${2:+"$2"} >/dev/null 2>&1 || true
  else
    "$CHROME" --user-data-dir="$1" --no-first-run --no-default-browser-check \
      --disable-sync --disable-background-networking \
      ${2:+"$2"} >/dev/null 2>&1 || true
  fi
}

case "$MODE" in
  check)
    RC=0
    if [ -n "$CFT" ]; then
      echo "✓ Chrome for Testing 可用，扩展随启动自动装载（无需 --init）"
      echo "  $CFT"
    elif grep -rqs "GeoLook" "$TEMPLATE/Default/Preferences" 2>/dev/null; then
      echo "✓ 沙箱模板已含扩展：$TEMPLATE"
    else
      echo "✗ 日常 Chrome 不支持自动装载扩展——跑 ./sandbox.sh --init 手动装一次"; RC=1
    fi
    if curl -fsS -m 3 http://127.0.0.1:8765/api/projects >/dev/null 2>&1; then
      echo "✓ 看板在线（127.0.0.1:8765）"
    else echo "✗ 看板没启动——另开一个终端跑：python3 scripts/geo.py ui"; RC=1; fi
    [ "$RC" = 0 ] && echo "闭环就绪：./sandbox.sh 起沙箱就能开始采样" || echo "先解决上面标 ✗ 的项"
    exit $RC ;;

  reset)
    rm -rf "$TEMPLATE"; echo "模板已删除：$TEMPLATE（下次跑 --init 重建）"; exit 0 ;;

  init)
    if [ -n "$CFT" ]; then
      echo "检测到 Chrome for Testing，扩展会随每次启动自动装载——无需初始化。"
      echo "直接运行：./sandbox.sh"
      exit 0
    fi
    mkdir -p "$TEMPLATE"
    cat <<EOF
即将打开沙箱浏览器。请在里面做一次性设置：

  1. 地址栏已打开 chrome://extensions
  2. 右上角打开「开发者模式」
  3. 点「加载已解压的扩展程序」，选择：
       $DIR
  4. 关掉浏览器窗口即可

装完之后，以后每次 ./sandbox.sh 起的沙箱都自带这个扩展。
EOF
    read -r -p "回车继续…" _
    launch "$TEMPLATE" "chrome://extensions"
    if grep -rqs "GeoLook" "$TEMPLATE/Default/Preferences" 2>/dev/null; then
      echo "✓ 扩展已装进模板：$TEMPLATE"
    else
      echo "⚠ 没检测到扩展，可能没装成功——重跑 ./sandbox.sh --init 再试一次"
    fi
    exit 0 ;;
esac

# CfT 引擎：扩展随启动装载，模板只是「持久登录态的家」，不需要预装扩展
if [ -z "$CFT" ] && [ ! -d "$TEMPLATE" ]; then
  echo "日常 Chrome 需要先初始化：./sandbox.sh --init" >&2; exit 1
fi

if [ "$MODE" = keep ]; then
  mkdir -p "$TEMPLATE"
  echo "模式：持久沙箱（登录态保留）· $TEMPLATE"
  echo "引擎：$([ -n "$CFT" ] && echo 'Chrome for Testing（扩展自动装载）' || echo '日常 Chrome（模板内已装扩展）')"
  echo "提示：插件侧栏「采样环境」选「专用采样 Profile」"
  launch "$TEMPLATE" "$URL"
  exit 0
fi

# 一次性沙箱
PROFILE="$(mktemp -d "${TMPDIR:-/tmp}/geolook-sandbox.XXXXXX")"
trap 'rm -rf "$PROFILE"' EXIT
if [ -z "$CFT" ]; then
  # 日常 Chrome：从模板复制（保留已装扩展），再清掉站点数据，等于全新浏览器
  cp -R "$TEMPLATE/." "$PROFILE/" 2>/dev/null || true
  # 扩展自身的数据在 Local Extension Settings/，不在下面这些里，删了不影响插件
  for junk in Cookies "Cookies-journal" History "History-journal" "Login Data" "Web Data" \
              "Local Storage" "Session Storage" "Service Worker" IndexedDB Sessions \
              "Network/Cookies" "Network/Network Persistent State" "Top Sites" Favicons; do
    rm -rf "$PROFILE/Default/$junk"
  done
fi
echo "模式：一次性沙箱（关闭后自动清除）"
echo "引擎：$([ -n "$CFT" ] && echo 'Chrome for Testing（扩展自动装载）' || echo '日常 Chrome（复制模板）')"
echo "提示：插件侧栏「采样环境」选「一次性沙箱」"
launch "$PROFILE" "$URL"
echo "已清除：$PROFILE"
