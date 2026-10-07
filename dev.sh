#!/usr/bin/env bash
# One menu for a checkout: 1 configure, 2 build, 3 run.
#
#   ./dev.sh        menu
#   ./dev.sh 1      toolchain, WoW link, server and account
#   ./dev.sh 2      cargo build --profile play -p benilla
#   ./dev.sh 3      run target/play/benilla
#
# Local paths and login are written to .benilla.local (gitignored) and exported
# for 2 and 3. The install itself stays the WoW link at the repo root.
set -euo pipefail

root="$(cd "$(dirname "$0")" && pwd)"
cd "$root"
local_env="$root/.benilla.local"

if [ -f "$HOME/.cargo/env" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.cargo/env"
fi

load_env() {
    if [ -f "$local_env" ]; then
        set -a
        # shellcheck disable=SC1090
        . "$local_env"
        set +a
    fi
}

load_env

# A vanilla Data directory: patch.MPQ is on every 1.12.1 install; terrain.MPQ is a base archive.
data_dir_ok() {
    [ -d "$1" ] || return 1
    ls -1 "$1" 2>/dev/null | grep -qiE '^(patch|terrain)\.mpq$'
}

has_data() {
    if [ -n "${WOW_DATA:-}" ] && data_dir_ok "$WOW_DATA"; then
        return 0
    fi
    data_dir_ok "$root/WoW/Data"
}

abs_dir() {
    (cd "$1" && pwd -P)
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1
}

pause() {
    printf '按回车继续… '
    read -r _
}

# ── 1. toolchain ────────────────────────────────────────────────────────────────────────────────

ensure_compiler() {
    case "$(uname -s)" in
    Darwin)
        if xcode-select -p >/dev/null 2>&1; then
            echo "  Xcode 命令行工具: 已安装"
            return 0
        fi
        echo "  未找到 Xcode 命令行工具（编译 Lua 和音频绑定需要它）。"
        echo "  正在打开安装窗口；装完后重新选 1。"
        xcode-select --install || true
        exit 1
        ;;
    Linux)
        if need_cmd cc || need_cmd gcc || need_cmd clang; then
            if need_cmd pkg-config; then
                echo "  C 编译器和 pkg-config: 已安装"
                return 0
            fi
        fi
        echo "  缺少 C 编译器或 pkg-config（还需要 ALSA 和 udev 的开发包）。"
        if need_cmd apt-get; then
            sudo apt-get update || return 1
            sudo apt-get install -y build-essential pkg-config libasound2-dev libudev-dev || return 1
        elif need_cmd dnf; then
            sudo dnf install -y gcc pkgconf-pkg-config alsa-lib-devel systemd-devel || return 1
        elif need_cmd pacman; then
            sudo pacman -S --needed base-devel pkgconf alsa-lib systemd || return 1
        else
            echo "  请按 docs/CONTRIBUTING.md 自行安装 ALSA、udev 开发包和 pkg-config。"
            return 1
        fi
        echo "  C 编译器和 pkg-config: 已安装"
        ;;
    *)
        echo "  此脚本覆盖 macOS 和 Linux。Windows 用 README 里的 PowerShell 命令。"
        exit 1
        ;;
    esac
}

ensure_rust() {
    if ! need_cmd rustup; then
        echo "  未找到 rustup，正在安装稳定版 Rust…"
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y || return 1
        # shellcheck disable=SC1091
        . "$HOME/.cargo/env"
    fi
    # rust-toolchain.toml pins the channel and clippy/rustfmt; this installs them.
    rustup show || return 1
    echo "  Rust: $(rustc --version)"
}

# ── 1. game data ────────────────────────────────────────────────────────────────────────────────

link_install() {
    local install="$1" current=""
    if [ -L "$root/WoW" ]; then
        current="$(abs_dir "$root/WoW" || true)"
    elif [ -e "$root/WoW" ]; then
        echo "  ./WoW 已存在且不是链接。移开它之后再选 1。"
        return 1
    fi
    if [ "$current" = "$install" ]; then
        echo "  数据: $root/WoW/Data"
        return 0
    fi
    ln -sfn "$install" "$root/WoW"
    echo "  已链接 ./WoW -> $install"
}

configure_data() {
    local input path parent
    if has_data; then
        if [ -n "${WOW_DATA:-}" ]; then
            echo "  当前数据: $WOW_DATA"
        else
            echo "  当前数据: $root/WoW/Data"
        fi
        printf '  新的客户端路径（直接回车保持不变）: '
    else
        echo "  需要你自己的英文 1.12.1 客户端（build 5875）。benilla 只读它。"
        printf '  客户端目录（里面有 Data）或 Data 目录本身: '
    fi
    read -r input
    if [ -z "$input" ]; then
        if has_data; then
            return 0
        fi
        echo "  未设置游戏数据。运行前需要它。"
        return 1
    fi
    path="$(abs_dir "$input")" || {
        echo "  目录不存在: $input"
        return 1
    }
    if data_dir_ok "$path/Data"; then
        link_install "$path" || return 1
        unset WOW_DATA
        return 0
    fi
    if data_dir_ok "$path"; then
        parent="$(dirname "$path")"
        case "$(basename "$path")" in
        [Dd]ata)
            link_install "$parent" || return 1
            unset WOW_DATA
            ;;
        *)
            WOW_DATA="$path"
            echo "  数据: $WOW_DATA"
            ;;
        esac
        return 0
    fi
    echo "  这里没有 1.12.1 的 Data（需要 patch.MPQ 或 terrain.MPQ）。"
    return 1
}

configure_server() {
    local input cur_host cur_user
    cur_host="${WOW_HOST:-localhost:3724}"
    cur_user="${WOW_USER:-}"
    echo "  服务器默认 localhost:3724。账号留空则在登录界面输入。"
    printf '  地址 [%s]: ' "$cur_host"
    read -r input
    WOW_HOST="${input:-$cur_host}"

    if [ -n "$cur_user" ]; then
        printf '  账号 [%s]（直接回车保持，输入 - 清除）: ' "$cur_user"
    else
        printf '  账号（直接回车跳过）: '
    fi
    read -r input
    if [ "$input" = "-" ]; then
        unset WOW_USER WOW_PASS WOW_CHAR
        echo "  已清除保存的账号。"
        return 0
    fi
    if [ -n "$input" ]; then
        WOW_USER="$input"
    elif [ -z "$cur_user" ]; then
        unset WOW_USER WOW_PASS WOW_CHAR
        return 0
    fi
    printf '  密码（不回显，直接回车保持不变）: '
    read -r -s input
    echo
    if [ -n "$input" ]; then
        WOW_PASS="$input"
    fi
    if [ -z "${WOW_PASS:-}" ]; then
        echo "  还没有密码，账号不会写入。"
        unset WOW_USER WOW_PASS WOW_CHAR
        return 0
    fi
    if [ -n "${WOW_CHAR:-}" ]; then
        printf '  角色名 [%s]（直接回车保持不变）: ' "$WOW_CHAR"
    else
        printf '  角色名（直接回车则进游戏后自己选）: '
    fi
    read -r input
    if [ -n "$input" ]; then
        WOW_CHAR="$input"
    fi
}

write_env() {
    local tmp old_umask
    tmp="$(mktemp "${TMPDIR:-/tmp}/benilla.local.XXXXXX")"
    old_umask="$(umask)"
    umask 077
    {
        echo "# sourced by dev.sh. gitignored."
        printf 'WOW_HOST=%q\n' "$WOW_HOST"
        if [ -n "${WOW_DATA:-}" ]; then
            printf 'WOW_DATA=%q\n' "$WOW_DATA"
        fi
        if [ -n "${WOW_USER:-}" ]; then
            printf 'WOW_USER=%q\n' "$WOW_USER"
            printf 'WOW_PASS=%q\n' "$WOW_PASS"
            if [ -n "${WOW_CHAR:-}" ]; then
                printf 'WOW_CHAR=%q\n' "$WOW_CHAR"
            fi
        fi
    } >"$tmp"
    umask "$old_umask"
    mv "$tmp" "$local_env"
    chmod 600 "$local_env"
}

configure() {
    echo "== 1 配置环境 =="
    echo "[工具链]"
    ensure_compiler || return 1
    ensure_rust || return 1
    echo "[游戏数据]"
    configure_data || return 1
    echo "[服务器]"
    configure_server || return 1
    write_env
    echo "配置已写入 .benilla.local。"
    echo "下一步: 选 2 编译，选 3 运行。"
}

# ── 2 and 3 ─────────────────────────────────────────────────────────────────────────────────────

export_run_env() {
    load_env
    export WOW_HOST="${WOW_HOST:-localhost:3724}"
    if [ -n "${WOW_DATA:-}" ]; then
        export WOW_DATA
    fi
    if [ -n "${WOW_USER:-}" ]; then
        export WOW_USER WOW_PASS
        if [ -n "${WOW_CHAR:-}" ]; then
            export WOW_CHAR
        fi
    fi
}

require_rust() {
    if ! need_cmd cargo; then
        echo "还没有 Rust。先选 1 配置环境。"
        return 1
    fi
}

build_client() {
    echo "== 2 编译 =="
    require_rust || return 1
    echo "cargo build --profile play -p benilla"
    cargo build --profile play -p benilla || return 1
    echo "编译完成: target/play/benilla"
}

run_client() {
    echo "== 3 运行 =="
    require_rust || return 1
    export_run_env
    if ! has_data; then
        echo "没有找到游戏数据。先选 1，指向你的 1.12.1 客户端。"
        return 1
    fi
    local bin="$root/target/play/benilla"
    if [ ! -x "$bin" ]; then
        echo "还没有可运行的程序。先选 2 编译。"
        return 1
    fi
    echo "服务器: $WOW_HOST"
    if [ -n "${WOW_USER:-}" ]; then
        echo "账号: $WOW_USER"
    else
        echo "账号: 登录界面输入"
    fi
    echo "运行: $bin"
    "$bin" || return 1
}

usage() {
    echo "用法: ./dev.sh [1|2|3]"
    echo "  1  配置环境"
    echo "  2  编译"
    echo "  3  运行"
}

menu() {
    echo
    echo "benilla"
    echo "  1) 配置环境"
    echo "  2) 编译"
    echo "  3) 运行"
    echo "  q) 退出"
    printf '选择 [1/2/3/q]: '
    read -r choice || exit 0
    case "$choice" in
    1) configure || true ;;
    2) build_client || true ;;
    3) run_client || true ;;
    q | Q) exit 0 ;;
    *) echo "请输入 1、2、3 或 q。" ;;
    esac
}

case "${1:-}" in
1) configure ;;
2) build_client ;;
3) run_client ;;
-h | --help) usage ;;
"")
    while true; do
        menu || true
        pause
    done
    ;;
*)
    usage
    exit 1
    ;;
esac
