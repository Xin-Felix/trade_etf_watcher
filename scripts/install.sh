#!/bin/bash
# 安装脚本：打包 → 清除隔离属性 → 签名 → 拷贝到 /Applications
set -e

cd "$(dirname "$0")/.."
echo "=== 开始打包 ==="
source .venv/bin/activate
pyinstaller build/macos.spec --distpath dist --workpath build/work --noconfirm --clean

echo ""
echo "=== 清除隔离/追溯属性 ==="
xattr -r -d com.apple.quarantine dist/日进斗金.app 2>/dev/null || true
xattr -r -d com.apple.provenance dist/日进斗金.app 2>/dev/null || true

echo ""
echo "=== 签名（ad-hoc + entitlements） ==="
codesign --force --deep --sign - --entitlements build/entitlements.plist dist/日进斗金.app

echo ""
echo "=== 安装到 /Applications ==="
rm -rf /Applications/日进斗金.app
cp -R dist/日进斗金.app /Applications/
# 拷贝后再清一次（cp 可能重新附加属性）
xattr -r -d com.apple.quarantine /Applications/日进斗金.app 2>/dev/null || true
xattr -r -d com.apple.provenance /Applications/日进斗金.app 2>/dev/null || true

echo ""
echo "=== 添加防火墙例外 ==="
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /Applications/日进斗金.app/Contents/MacOS/日进斗金 2>/dev/null || true
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp /Applications/日进斗金.app/Contents/MacOS/日进斗金 2>/dev/null || true

echo ""
echo "=== 完成！==="
echo "现在可以从 /Applications 启动「日进斗金」了"
