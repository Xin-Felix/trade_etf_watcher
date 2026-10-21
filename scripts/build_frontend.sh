#!/usr/bin/env bash
#
# 前端构建 + Qt 资源编译（唯一入口）
#
# 改了 frontend/ 下的任何东西，或改了 watcher/gui/web/*.html，都跑这个脚本。
# 它把三步串起来，避免漏掉最后一步导致「改了页面但运行时还是旧版」：
#   1. vite build            → frontend/dist/index.html（单文件，JS/CSS 全内联）
#   2. cp                    → watcher/gui/web/app.html
#   3. pyside6-rcc           → watcher/gui/web/web_resources.py
#
# 页面是从 qrc 读的（webtab.py 里 QFile(":/web/...")），
# 只改 HTML 不重新编译 qrc 的话，运行时加载的仍是旧内容。
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="$ROOT/watcher/gui/web"
FRONTEND="$ROOT/frontend"

# pyside6-rcc：优先用项目 venv 里的，保证和运行时 PySide6 版本一致
RCC="$ROOT/.venv/bin/pyside6-rcc"
if [ ! -x "$RCC" ]; then
  RCC="$(command -v pyside6-rcc || true)"
fi
if [ -z "$RCC" ]; then
  echo "错误：找不到 pyside6-rcc，请先安装 PySide6（或激活 .venv）" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "错误：找不到 npm。改前端需要 Node.js；" >&2
  echo "      只想打包已有版本的话不用跑本脚本，web_resources.py 已在仓库里。" >&2
  exit 1
fi

echo "==> 1/3 构建 Vue 前端"
cd "$FRONTEND"
if [ ! -d node_modules ]; then
  echo "    node_modules 缺失，安装依赖…"
  npm ci 2>/dev/null || npm install
fi
npm run build

DIST="$FRONTEND/dist/index.html"
if [ ! -f "$DIST" ]; then
  echo "错误：构建产物不存在：$DIST" >&2
  exit 1
fi

echo "==> 2/3 拷贝产物 → watcher/gui/web/app.html"
cp "$DIST" "$WEB/app.html"
echo "    app.html          $(du -h "$WEB/app.html" | cut -f1)"

echo "==> 3/3 编译 Qt 资源（qrc）"
cd "$WEB"
"$RCC" web_resources.qrc -o web_resources.py
echo "    web_resources.py  $(du -h web_resources.py | cut -f1)"

echo
echo "完成。改动已进入 qrc，重启应用即生效。"
