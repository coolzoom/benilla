#!/usr/bin/env bash
# The Android build: toolchain, cross-compile, APK, push and launch, in one script.
#
#   ./android.sh            menu
#   ./android.sh 1          JDK, Android SDK, NDK into _work/, the rustup target
#   ./android.sh 2          cargo build of crates/benilla-android for arm64-v8a
#   ./android.sh 3          _work/out/benilla.apk (NativeActivity, no Java code)
#   ./android.sh 4          adb install, benilla.env, adb reverse, game data if missing, launch
#   ./android.sh 5          1 to 4
#   ./android.sh data       adb push the WoW Data folder (several GB) on its own
#   ./android.sh install    and `run`: the two halves of 4
#
# Switches (environment):
#   ANDROID_PROFILE=release|ship|play   cargo profile (default release)
#   ANDROID_DEV=1                       build with the `dev` feature (instruments, egui panel)
#   ANDROID_SERIAL=<id>                 which device adb talks to
#   ANDROID_REVERSE=0                   skip `adb reverse` of the server ports
#
# Everything downloaded lives in _work/ (gitignored). The game data is the player's own and is
# copied into the app's internal files folder through `run-as`, never packed into the APK.
set -euo pipefail

root="$(cd "$(dirname "$0")" && pwd)"
cd "$root"
work="$root/_work"
out="$work/out"

PKG="org.benilla.client"
LIB="benilla_android"
ABI="arm64-v8a"
TARGET="aarch64-linux-android"
API=26
SDK_PLATFORM=35
BUILD_TOOLS=35.0.0
NDK_VERSION=27.2.12479018
NDK_RELEASE=r27c
CMDLINE_TOOLS=13114758
PROFILE="${ANDROID_PROFILE:-release}"
# The app's internal files folder (benilla-android's `android_main`), written through `run-as`.
DEVICE_DIR="/data/user/0/$PKG/files"
STAGE="/data/local/tmp/benilla-stage"

export ANDROID_HOME="${ANDROID_HOME:-$work/android-sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
NDK="${ANDROID_NDK_HOME:-$ANDROID_HOME/ndk/$NDK_VERSION}"

if [ -f "$HOME/.cargo/env" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.cargo/env"
fi
if [ -f "$root/.benilla.local" ]; then
    set -a
    # shellcheck disable=SC1091
    . "$root/.benilla.local"
    set +a
fi

say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die() {
    printf '\033[1;31m错误:\033[0m %s\n' "$*" >&2
    exit 1
}
need_cmd() { command -v "$1" >/dev/null 2>&1; }

host_tag() {
    case "$(uname -s)" in
    Darwin) echo darwin-x86_64 ;; # the NDK ships universal binaries under this name
    Linux) echo linux-x86_64 ;;
    *) die "只支持 macOS 和 Linux 主机" ;;
    esac
}

fetch() {
    local url="$1" dest="$2"
    if [ -f "$dest" ]; then
        return 0
    fi
    say "下载 $url"
    # `-C -` resumes a `.part` an interrupted run left behind.
    curl -fL --retry 5 --retry-all-errors -C - -o "$dest.part" "$url"
    mv "$dest.part" "$dest"
}

# ── setup ───────────────────────────────────────────────────────────────────────────────────────

java_ok() {
    local v
    need_cmd java || return 1
    v="$(java -version 2>&1 | awk -F'"' '/version/ {print $2}' | cut -d. -f1)"
    [ -n "$v" ] && [ "$v" -ge 17 ] 2>/dev/null
}

ensure_java() {
    if [ -x "$work/jdk/bin/java" ]; then
        export JAVA_HOME="$work/jdk" PATH="$work/jdk/bin:$PATH"
    fi
    if java_ok; then
        say "Java: $(java -version 2>&1 | head -1)"
        return 0
    fi
    local os arch archive
    case "$(uname -s)" in Darwin) os=mac ;; *) os=linux ;; esac
    case "$(uname -m)" in arm64 | aarch64) arch=aarch64 ;; *) arch=x64 ;; esac
    archive="$work/dl/jdk-21-$os-$arch.tar.gz"
    fetch "https://api.adoptium.net/v3/binary/latest/21/ga/$os/$arch/jdk/hotspot/normal/eclipse" "$archive"
    rm -rf "$work/jdk.tmp" && mkdir -p "$work/jdk.tmp"
    tar -xzf "$archive" -C "$work/jdk.tmp"
    local home
    home="$(find "$work/jdk.tmp" -maxdepth 4 -type f -path '*/bin/java' | head -1)"
    home="$(dirname "$(dirname "$home")")"
    rm -rf "$work/jdk" && mv "$home" "$work/jdk" && rm -rf "$work/jdk.tmp"
    export JAVA_HOME="$work/jdk" PATH="$work/jdk/bin:$PATH"
    java_ok || die "JDK 安装失败"
    say "Java: $(java -version 2>&1 | head -1)"
}

sdkmanager_bin() { echo "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"; }

ensure_sdk() {
    local os archive
    if [ ! -x "$(sdkmanager_bin)" ]; then
        case "$(uname -s)" in Darwin) os=mac ;; *) os=linux ;; esac
        archive="$work/dl/commandlinetools-$os-${CMDLINE_TOOLS}_latest.zip"
        fetch "https://dl.google.com/android/repository/commandlinetools-$os-${CMDLINE_TOOLS}_latest.zip" "$archive"
        rm -rf "$work/cmdline-tools.tmp" && mkdir -p "$work/cmdline-tools.tmp" "$ANDROID_HOME/cmdline-tools"
        unzip -q "$archive" -d "$work/cmdline-tools.tmp"
        rm -rf "$ANDROID_HOME/cmdline-tools/latest"
        mv "$work/cmdline-tools.tmp/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest"
        rm -rf "$work/cmdline-tools.tmp"
    fi
    local want=()
    # An interrupted install leaves a partial folder, and sdkmanager then installs beside it as
    # `<name>-2`; clear both so the package lands where the checks look.
    want_pkg() {
        local check="$1" pkg="$2" dir="$3"
        [ -e "$check" ] && return 0
        rm -rf "$ANDROID_HOME/$dir" "$ANDROID_HOME/$dir"-[0-9]*
        want+=("$pkg")
    }
    want_pkg "$ANDROID_HOME/platform-tools/adb" "platform-tools" "platform-tools"
    want_pkg "$ANDROID_HOME/build-tools/$BUILD_TOOLS/apksigner" "build-tools;$BUILD_TOOLS" "build-tools/$BUILD_TOOLS"
    want_pkg "$ANDROID_HOME/platforms/android-$SDK_PLATFORM/android.jar" \
        "platforms;android-$SDK_PLATFORM" "platforms/android-$SDK_PLATFORM"
    rm -rf "$ANDROID_HOME/build-tools/$BUILD_TOOLS"-[0-9]* "$ANDROID_HOME/platforms/android-$SDK_PLATFORM"-[0-9]*
    if [ "${#want[@]}" -gt 0 ]; then
        rm -rf "$ANDROID_HOME/.temp"
        say "sdkmanager: ${want[*]}"
        yes | "$(sdkmanager_bin)" --sdk_root="$ANDROID_HOME" --licenses >/dev/null || true
        "$(sdkmanager_bin)" --sdk_root="$ANDROID_HOME" "${want[@]}"
    fi
    ensure_ndk
    say "SDK: $ANDROID_HOME"
    say "NDK: $NDK"
}

# The NDK by curl, not sdkmanager: the same zip, resumable, and sdkmanager's own download crawls.
ensure_ndk() {
    [ -d "$NDK/toolchains/llvm" ] && return 0
    local os archive
    case "$(uname -s)" in Darwin) os=darwin ;; *) os=linux ;; esac
    archive="$work/dl/android-ndk-$NDK_RELEASE-$os.zip"
    say "NDK ${NDK_RELEASE}（约 800 MB）"
    fetch "https://dl.google.com/android/repository/android-ndk-$NDK_RELEASE-$os.zip" "$archive"
    if ! unzip -tq "$archive" >/dev/null 2>&1; then
        say "NDK 压缩包损坏，重新下载"
        rm -f "$archive"
        fetch "https://dl.google.com/android/repository/android-ndk-$NDK_RELEASE-$os.zip" "$archive"
        unzip -tq "$archive" >/dev/null 2>&1 || {
            rm -f "$archive"
            die "NDK 压缩包仍然损坏，请重试"
        }
    fi
    say "解压 NDK -> $NDK"
    rm -rf "$work/ndk.tmp" && mkdir -p "$work/ndk.tmp" "$(dirname "$NDK")"
    unzip -q "$archive" -d "$work/ndk.tmp"
    rm -rf "$NDK"
    mv "$work/ndk.tmp/android-ndk-$NDK_RELEASE" "$NDK"
    rm -rf "$work/ndk.tmp"
}

ensure_rust_target() {
    need_cmd rustup || die "没有 rustup，先运行 ./dev.sh 1"
    # rust-toolchain.toml pins the channel; the target is added to that toolchain.
    rustup target list --installed | grep -qx "$TARGET" || rustup target add "$TARGET"
    say "Rust: $(rustc --version), target $TARGET"
}

# One setup at a time: two runs append to the same `.part` download and corrupt it.
setup_lock() {
    local lock="$work/.setup.lock"
    if ! mkdir "$lock" 2>/dev/null; then
        if kill -0 "$(cat "$lock/pid" 2>/dev/null)" 2>/dev/null; then
            die "另一个 ./android.sh 1 正在运行（pid $(cat "$lock/pid")）"
        fi
        rm -rf "$lock" && mkdir "$lock"
    fi
    echo $$ >"$lock/pid"
    trap 'rm -rf "$work/.setup.lock"' EXIT
}

setup() {
    mkdir -p "$work/dl" "$out"
    setup_lock
    ensure_java
    ensure_sdk
    ensure_rust_target
}

# ── build ───────────────────────────────────────────────────────────────────────────────────────

toolchain_env() {
    local tc="$NDK/toolchains/llvm/prebuilt/$(host_tag)"
    [ -d "$tc" ] || die "NDK 不完整: ${tc}（先运行 ./android.sh setup）"
    local cc="$tc/bin/$TARGET$API-clang"
    export TOOLCHAIN_BIN="$tc/bin"
    export ANDROID_NDK_HOME="$NDK" ANDROID_NDK_ROOT="$NDK" NDK_HOME="$NDK"
    export CC_aarch64_linux_android="$cc"
    export CXX_aarch64_linux_android="$cc++"
    export AR_aarch64_linux_android="$tc/bin/llvm-ar"
    export RANLIB_aarch64_linux_android="$tc/bin/llvm-ranlib"
    export CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER="$cc"
    export CARGO_TARGET_AARCH64_LINUX_ANDROID_AR="$tc/bin/llvm-ar"
    export BINDGEN_EXTRA_CLANG_ARGS_aarch64_linux_android="--sysroot=$tc/sysroot"
}

build() {
    toolchain_env
    local features=()
    if [ "${ANDROID_DEV:-0}" = 1 ]; then
        features=(--features dev)
    fi
    say "cargo build -p benilla-android --target $TARGET --profile $PROFILE ${features[*]:-}"
    cargo build -p benilla-android --lib --target "$TARGET" --profile "$PROFILE" ${features[@]+"${features[@]}"}
    say "完成: $(so_path)"
}

so_path() {
    local dir="$PROFILE"
    [ "$PROFILE" = dev ] && dir=debug
    echo "${CARGO_TARGET_DIR:-$root/target}/$TARGET/$dir/lib$LIB.so"
}

# ── package ─────────────────────────────────────────────────────────────────────────────────────

write_manifest() {
    local version
    version="$(awk -F'"' '/^version *=/ {print $2; exit}' "$root/Cargo.toml")"
    cat >"$1" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="$PKG"
    android:versionCode="1"
    android:versionName="$version">
    <uses-sdk android:minSdkVersion="$API" android:targetSdkVersion="$SDK_PLATFORM" />
    <uses-feature android:name="android.hardware.vulkan.level" android:version="1" android:required="true" />
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
    <application
        android:label="benilla"
        android:hasCode="false"
        android:extractNativeLibs="true"
        android:debuggable="true"
        android:requestLegacyExternalStorage="true">
        <activity
            android:name="android.app.NativeActivity"
            android:exported="true"
            android:launchMode="singleTask"
            android:screenOrientation="sensorLandscape"
            android:theme="@android:style/Theme.NoTitleBar.Fullscreen"
            android:configChanges="orientation|screenSize|screenLayout|smallestScreenSize|keyboard|keyboardHidden|navigation|uiMode|density">
            <meta-data android:name="android.app.lib_name" android:value="$LIB" />
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
EOF
}

debug_keystore() {
    local ks="$work/debug.keystore"
    if [ ! -f "$ks" ]; then
        keytool -genkeypair -keystore "$ks" -storepass android -keypass android \
            -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
            -dname "CN=Android Debug,O=Android,C=US" >/dev/null
    fi
    echo "$ks"
}

package() {
    toolchain_env
    ensure_java
    local so bt stage apk
    so="$(so_path)"
    [ -f "$so" ] || die "没有 ${so}（先运行 ./android.sh build）"
    bt="$ANDROID_HOME/build-tools/$BUILD_TOOLS"
    stage="$work/apk"
    apk="$out/benilla.apk"
    rm -rf "$stage" && mkdir -p "$stage/lib/$ABI" "$out"

    say "strip -> lib/$ABI/lib$LIB.so"
    "$TOOLCHAIN_BIN/llvm-strip" --strip-all -o "$stage/lib/$ABI/lib$LIB.so" "$so"
    # Ship libc++_shared.so only when something in the graph links it.
    if "$TOOLCHAIN_BIN/llvm-readelf" -d "$so" | grep -q 'libc++_shared.so'; then
        cp "$TOOLCHAIN_BIN/../sysroot/usr/lib/$TARGET/libc++_shared.so" "$stage/lib/$ABI/"
        say "附带 libc++_shared.so"
    fi

    write_manifest "$stage/AndroidManifest.xml"
    "$bt/aapt2" link -o "$stage/base.apk" \
        --manifest "$stage/AndroidManifest.xml" \
        -I "$ANDROID_HOME/platforms/android-$SDK_PLATFORM/android.jar"
    (cd "$stage" && zip -q -r base.apk lib)
    "$bt/zipalign" -f -p 4 "$stage/base.apk" "$stage/aligned.apk"
    "$bt/apksigner" sign --ks "$(debug_keystore)" --ks-pass pass:android \
        --key-pass pass:android --out "$apk" "$stage/aligned.apk"
    say "APK: $apk ($(du -h "$apk" | cut -f1))"
}

# ── device ──────────────────────────────────────────────────────────────────────────────────────

adb_() {
    "$ANDROID_HOME/platform-tools/adb" ${ANDROID_SERIAL:+-s "$ANDROID_SERIAL"} "$@"
}

require_device() {
    [ -x "$ANDROID_HOME/platform-tools/adb" ] || die "没有 adb（先运行 ./android.sh setup）"
    local n addr
    n="$(adb_ devices | awk 'NR>1 && $2=="device"' | wc -l | tr -d ' ')"
    # No USB device: try the emulators' adb ports (MuMu on macOS 16384, or 16385 after a restart;
    # others 5555), or ANDROID_CONNECT=<host:port>.
    if [ "$n" -lt 1 ]; then
        for addr in ${ANDROID_CONNECT:-127.0.0.1:16384 127.0.0.1:16385 127.0.0.1:5555}; do
            if adb_ connect "$addr" 2>/dev/null | grep -q '^connected'; then
                say "adb connect $addr"
                export ANDROID_SERIAL="$addr"
                n=1
                break
            fi
        done
    fi
    [ "$n" -ge 1 ] || die "没有已授权的设备。打开 USB 调试并在手机上允许这台电脑。"
    if [ "$n" -gt 1 ] && [ -z "${ANDROID_SERIAL:-}" ]; then
        adb_ devices
        die "有多台设备，用 ANDROID_SERIAL=<id> 指定一台"
    fi
}

# The server address as the device sees it: `localhost` goes through `adb reverse`.
device_host() {
    echo "${WOW_HOST:-localhost:3724}"
}

write_device_env() {
    local f="$1"
    {
        echo "# benilla.env: read by the Android launcher at startup, KEY=VALUE per line."
        echo "WOW_HOST=$(device_host)"
        [ -n "${WOW_USER:-}" ] && echo "WOW_USER=$WOW_USER"
        [ -n "${WOW_PASS:-}" ] && echo "WOW_PASS=$WOW_PASS"
        [ -n "${WOW_CHAR:-}" ] && echo "WOW_CHAR=$WOW_CHAR"
        # benilla reads the variable's presence, not its value: an empty line would mute too.
        [ -n "${WOW_NOSOUND:-}" ] && echo "WOW_NOSOUND=$WOW_NOSOUND"
        # An emulator's goldfish Vulkan encoder hangs under concurrent calls (benilla_world::boot).
        if adb_ shell ls /system/lib64/libvulkan_enc.so >/dev/null 2>&1; then
            echo "WOW_GPU_SERIAL=1"
        fi
        # wgpu's backend override (`vulkan`, `gl`), passed through when set here.
        [ -n "${WGPU_BACKEND:-}" ] && echo "WGPU_BACKEND=$WGPU_BACKEND"
    } >"$f"
    chmod 600 "$f"
}

reverse_ports() {
    [ "${ANDROID_REVERSE:-1}" = 1 ] || return 0
    local host port
    host="$(device_host)"
    case "$host" in
    localhost* | 127.0.0.1*) ;;
    *) return 0 ;;
    esac
    port="${host##*:}"
    [ "$port" = "$host" ] && port=3724
    # realmd, and the world port a local 1.12 server hands out in its realm list.
    for p in "$port" "${WOW_WORLD_PORT:-8085}"; do
        adb_ reverse "tcp:$p" "tcp:$p" >/dev/null
        say "adb reverse tcp:${p}（设备上的 localhost:$p 指向这台电脑）"
    done
}

install_apk() {
    require_device
    local apk="$out/benilla.apk"
    [ -f "$apk" ] || die "没有 ${apk}（先运行 ./android.sh package）"
    say "adb install $apk"
    adb_ install -r -d "$apk"
    write_device_env "$work/benilla.env"
    stage_in "$work/benilla.env" "$DEVICE_DIR/benilla.env"
    say "已写入 $DEVICE_DIR/benilla.env（服务器 $(device_host)）"
    reverse_ports
}

# A shell command as the app itself (`android:debuggable`), so what it writes is the app's own.
as_app() {
    adb_ shell run-as "$PKG" sh -c "'$1'"
}

# Push `src` (a file, or a folder's contents) to `dest` in the app's folder: adb pushes into the
# shell's staging folder, and the app copies it in.
stage_in() {
    local src="$1" dest="$2"
    adb_ shell rm -rf "$STAGE" && adb_ shell mkdir -p "$STAGE"
    if [ -d "$src" ]; then
        adb_ push "$src/." "$STAGE/"
    else
        adb_ push "$src" "$STAGE/" >/dev/null
    fi
    adb_ shell chmod -R a+rX "$STAGE"
    if [ -d "$src" ]; then
        as_app "mkdir -p $dest && cp -R $STAGE/. $dest/"
    else
        as_app "mkdir -p $(dirname "$dest") && cp $STAGE/$(basename "$src") $dest"
    fi
    adb_ shell rm -rf "$STAGE"
}

# A vanilla Data folder on the device, by the same test as dev.sh's.
device_has_data() {
    as_app "ls $DEVICE_DIR/WoW/Data" 2>/dev/null | tr -d '\r' | grep -qiE '^(patch|terrain)\.mpq$'
}

local_data_dir() {
    if [ -n "${WOW_DATA:-}" ] && [ -d "$WOW_DATA" ]; then
        echo "$WOW_DATA"
    elif [ -d "$root/WoW/Data" ]; then
        (cd "$root/WoW/Data" && pwd -P)
    else
        die "本地没有游戏数据（./WoW/Data 或 WOW_DATA）"
    fi
}

push_data() {
    require_device
    local src
    src="$(local_data_dir)"
    say "推送 $src -> $DEVICE_DIR/WoW/Data（$(du -sh "$src" | cut -f1)，需要一些时间）"
    stage_in "$src" "$DEVICE_DIR/WoW/Data"
    say "游戏数据已推送"
}

run_app() {
    require_device
    reverse_ports
    adb_ shell am force-stop "$PKG" || true
    adb_ logcat -c || true
    say "启动 $PKG"
    adb_ shell am start -n "$PKG/android.app.NativeActivity" >/dev/null
    say "logcat（Ctrl-C 结束跟踪，应用继续运行）"
    local pid=""
    for _ in $(seq 1 20); do
        pid="$(adb_ shell pidof "$PKG" 2>/dev/null | tr -d '\r')"
        [ -n "$pid" ] && break
        sleep 0.5
    done
    if [ -n "$pid" ]; then
        adb_ logcat --pid="$pid"
    else
        adb_ logcat -s benilla:V RustStdoutStderr:V AndroidRuntime:E DEBUG:V
    fi
}

# Install, offer the game data when the device has none, launch.
deploy() {
    install_apk
    if ! device_has_data; then
        local answer=""
        printf '设备上还没有游戏数据。现在推送 %s？[y/N] ' "$(local_data_dir)"
        read -r answer || true
        case "$answer" in
        y | Y) push_data ;;
        *) printf '\033[1;33m注意:\033[0m 没有数据时客户端无法进入游戏，之后可运行 ./android.sh data。\n' ;;
        esac
    fi
    run_app
}

all() {
    setup
    build
    package
    deploy
}

usage() {
    echo "用法: ./android.sh [1|2|3|4|5|data]"
    echo "  1  安装环境（JDK、Android SDK、NDK 到 _work/，Rust 安卓目标）"
    echo "  2  编译（crates/benilla-android，arm64-v8a）"
    echo "  3  打包 APK（_work/out/benilla.apk）"
    echo "  4  推送到设备并运行（adb install、benilla.env、游戏数据、logcat）"
    echo "  5  全部（1 到 4）"
    echo "  data  只推送游戏数据"
    echo "环境变量: ANDROID_PROFILE=release|ship|play  ANDROID_DEV=1  ANDROID_SERIAL=<id>  ANDROID_REVERSE=0"
}

# Each step as its own process, so a failed step returns to the menu; a `( … ) || true` subshell
# would run with `set -e` off and carry on past the failure.
menu() {
    local choice=""
    echo
    echo "benilla 安卓"
    echo "  1) 安装环境"
    echo "  2) 编译"
    echo "  3) 打包 APK"
    echo "  4) 推送到设备并运行"
    echo "  5) 全部（1 到 4）"
    echo "  q) 退出"
    printf '选择 [1/2/3/4/5/q]: '
    read -r choice || exit 0
    case "$choice" in
    [1-5]) bash "$0" "$choice" || echo "步骤 $choice 失败。" ;;
    q | Q) exit 0 ;;
    *) echo "请输入 1、2、3、4、5 或 q。" ;;
    esac
}

case "${1:-}" in
1 | setup) setup ;;
2 | build) build ;;
3 | package) package ;;
4 | deploy) deploy ;;
5 | all) all ;;
install) install_apk ;;
data) push_data ;;
run) run_app ;;
-h | --help) usage ;;
"")
    while true; do
        menu
        printf '按回车继续… '
        read -r _ || exit 0
    done
    ;;
*)
    usage
    exit 1
    ;;
esac
