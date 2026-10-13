#!/usr/bin/env bash
# Install SideStore on a plugged-in iPhone so it can install an .ipa (iNilla's).
#
# SideStore's own install doc (docs.sidestore.io) uses iloader, from the one
# repository the iloader project names as official: github.com/nab138/iloader.
# This script downloads that release, checks the sha256 GitHub publishes for
# the asset, and opens it. The Apple Account password and the 2FA code are
# typed into iloader's window; this script never reads or stores them.
#
#   ios/sidestore.sh          download iloader, open it, print the phone steps
#   ios/sidestore.sh ipa      how to install target/inilla-ios-out/iNilla.ipa
#                             once SideStore is on the phone
#
# After SideStore is installed, an .ipa goes in through SideStore → My Apps →
# ＋, which re-signs it. See docs/IOS-BUILD.md, "Installing".
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
work="$root/_work/ios"
ipa_default="$root/target/inilla-ios-out/iNilla.ipa"
# iloader's README: this repository is the only official download.
iloader_repo="nab138/iloader"
iloader_api="https://api.github.com/repos/${iloader_repo}/releases/latest"

say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die() {
    printf '\033[1;31m错误:\033[0m %s\n' "$*" >&2
    exit 1
}
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "没有 $1"; }

host_asset() {
    case "$(uname -s)" in
    Darwin) echo "iloader-darwin-universal.app.tar.gz" ;;
    Linux)
        case "$(uname -m)" in
        x86_64) echo "iloader-linux-amd64.AppImage" ;;
        aarch64 | arm64) echo "iloader-linux-aarch64.AppImage" ;;
        *) die "iloader 没有 $(uname -m) 的 Linux 构建" ;;
        esac
        ;;
    *) die "只支持 macOS 和 Linux。Windows 用官方 iloader MSI：https://github.com/${iloader_repo}/releases/latest" ;;
    esac
}

# url, sha256 and tag of the official asset, one per line.
release_meta() {
    local asset="$1"
    python3 - "$iloader_api" "$asset" "$iloader_repo" <<'PY'
import json, sys, urllib.request

api, asset, repo = sys.argv[1:]
req = urllib.request.Request(
    api,
    headers={"Accept": "application/vnd.github+json", "User-Agent": "benilla-sidestore"},
)
with urllib.request.urlopen(req, timeout=60) as response:
    data = json.load(response)
want = f"https://github.com/{repo}/releases/download/"
for item in data.get("assets", []):
    if item.get("name") != asset:
        continue
    url = item["browser_download_url"]
    digest = item.get("digest") or ""
    if not url.startswith(want) or not digest.startswith("sha256:"):
        sys.exit(f"发布资源不可用: {url} {digest}")
    print(url)
    print(digest.split(":", 1)[1])
    print(data.get("tag_name", ""))
    sys.exit(0)
sys.exit(f"最新发布里没有 {asset}")
PY
}

sha256_file() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        sha256sum "$1" | awk '{print $1}'
    fi
}

download_iloader() {
    local asset archive meta url sha tag got
    asset="$(host_asset)"
    archive="$work/dl/$asset"
    mkdir -p "$work/dl"
    say "查询 ${iloader_repo} 的最新发布"
    meta="$(release_meta "$asset")"
    url="$(printf '%s\n' "$meta" | sed -n 1p)"
    sha="$(printf '%s\n' "$meta" | sed -n 2p)"
    tag="$(printf '%s\n' "$meta" | sed -n 3p)"
    [ -n "$url" ] && [ -n "$sha" ] || die "没有拿到 iloader 的下载地址"
    if [ -f "$archive" ] && [ "$(sha256_file "$archive")" = "$sha" ]; then
        say "已有校验通过的 $asset（$tag）"
        return 0
    fi
    say "下载 $url"
    curl -fL --retry 5 --retry-all-errors -A benilla-sidestore -o "$archive.part" "$url"
    got="$(sha256_file "$archive.part")"
    if [ "$got" != "$sha" ]; then
        rm -f "$archive.part"
        die "校验失败：下载到 $got，发布页是 $sha"
    fi
    mv "$archive.part" "$archive"
    say "校验通过（$tag）"
}

open_iloader() {
    local asset="$work/dl/$(host_asset)" app
    case "$(uname -s)" in
    Darwin)
        rm -rf "$work/iloader"
        mkdir -p "$work/iloader"
        tar -xzf "$asset" -C "$work/iloader"
        app="$(find "$work/iloader" -type d -name 'iloader.app' -print -quit)"
        [ -n "$app" ] || die "压缩包里没有 iloader.app"
        xattr -dr com.apple.quarantine "$app" 2>/dev/null || true
        say "打开 $app"
        open "$app"
        ;;
    Linux)
        chmod +x "$asset"
        say "启动 $asset"
        nohup "$asset" >/dev/null 2>&1 &
        disown || true
        ;;
    esac
}

list_devices() {
    say "查找已连接的 iPhone / iPad"
    if command -v xcrun >/dev/null 2>&1 && xcrun devicectl list devices >/dev/null 2>&1; then
        xcrun devicectl list devices || true
        return 0
    fi
    if [ "$(uname -s)" = "Darwin" ]; then
        system_profiler SPUSBDataType 2>/dev/null | awk '
            /iPhone|iPad|iPod/ { hit=1 }
            hit { print }
            hit && /^$/ { exit }
        ' || true
    fi
    printf '没有从这里看到设备也没关系：用数据线连上，在手机上点「信任」，iloader 窗口里会列出它。\n'
}

phone_steps() {
    cat <<'EOF'

接下来在 iloader 窗口里（Apple 账号只在那里登录，这个脚本不读取密码）：

  1. 用数据线连上 iPhone。手机弹出提示时点「信任」，并输入锁屏密码。
  2. 在 iloader 里登录 Apple 账号。邮箱区分大小写，不必是这台手机的账号。
  3. 选中这台手机。
  4. 选 Install SideStore (Stable)，等到它提示安装完成。

然后在手机上：

  1. 设置 → 通用 → VPN 与设备管理 → 信任刚才那个 Apple 账号。
  2. iOS 16 及以上：设置 → 隐私与安全性 → 开发者模式。打开后手机会重启，重启后再打开一次确认。
  3. 在 App Store 安装 LocalDevVPN，打开并点 Connect。之后每次在 SideStore 里安装或刷新应用，都要先连上它。
  4. 打开 SideStore，用同一个 Apple 账号登录。
  5. 我的 App → 点 SideStore 右边的「7 DAYS」刷新一次。它问要不要新建签名证书时选刷新。

免费 Apple 账号签的应用 7 天后过期，在 SideStore 里刷新即可，游戏数据和设置还在。
同时最多 3 个侧载应用，SideStore 自己占一个。

装 iNilla.ipa：SideStore → 我的 App → ＋ → 选中 .ipa。
不想再占一个名额时，先在 SideStore 里安装 LiveContainer，再把 .ipa 导入 LiveContainer
（先有 SideStore，再通过它装 LiveContainer）。

若 SideStore 本身装不上：iNilla 的安装说明指向社区的 SideInstaller，且只认这两处
  https://github.com/FrizzleM/SideInstaller
  https://frizzlem.github.io/SideInstaller/
不要安装其他网站、频道里的同名包。
EOF
}

ipa_steps() {
    local ipa="${1:-$ipa_default}"
    echo
    if [ -f "$ipa" ]; then
        say "IPA: $ipa ($(du -h "$ipa" | cut -f1))"
        if [ "$(uname -s)" = "Darwin" ]; then
            open -R "$ipa"
            echo "Finder 已选中它。隔空投送到手机，或在「文件」App 里打开，再用 SideStore → 我的 App → ＋ 选它。"
        fi
    else
        echo "还没有 $ipa。"
        echo "在 Mac 上先运行 ios/package-ipa.sh，或用 GitHub Actions 的 inilla-ipa 下载成品。"
    fi
    cat <<'EOF'

手机上（SideStore 已经按上面的步骤装好并刷新过）：

  SideStore → 我的 App → ＋ → 选 iNilla 的 .ipa。
  同一个 bundle id 再装一次就是更新，Documents 里的游戏数据还在。
  装完第一次打开时，按 docs/DATA.md 把游戏数据放进去。
EOF
}

usage() {
    echo "用法: ios/sidestore.sh [ipa [文件]]"
    echo "  （无参数）  下载官方 iloader 并打开，用于把 SideStore 装到已连接的 iPhone"
    echo "  ipa         SideStore 装好之后，怎么把 iNilla.ipa 装进手机"
}

case "${1:-}" in
-h | --help) usage ;;
ipa)
    ipa_steps "${2:-}"
    ;;
"")
    need_cmd curl
    need_cmd python3
    download_iloader
    list_devices
    open_iloader
    phone_steps
    ipa_steps
    ;;
*)
    usage
    exit 1
    ;;
esac
