# benilla 开发提速说明

记录时间：2026-10-12

## 1. 结论

| 操作 | 以前 | 现在（实测） |
|---|---|---|
| 改 `benilla-app` 后查编译错误 | — | 约 10 秒 |
| 改 `benilla-app` 后编译加链接桌面版 | 十几到二十分钟 | 约 20 秒 |
| 改代码后重新打安卓 debug APK | 十几分钟 | 约 19 秒 |
| 第一次全量编译（只发生一次） | — | 桌面约 16 分钟，安卓约 11 到 15 分钟 |

三个副本（`benilla-main`、`benilla-twow-main`、`benilla-twow-clone`）现在共用一个编译缓存
`D:\pc-soft\wow-benilla\_target`，不会每个副本各占一份，也不会每编一次就多一份。

## 2. 为什么以前慢

1. **用的是 `cargo build --release`。** release 不做增量编译。作者在 `Cargo.toml` 里自己记录过：
   在 macOS 上开着 sccache，改一行都要 2 分 47 秒；Windows 上更慢。
2. **代码几乎都在一个 crate 里。** `crates/benilla-app/src` 下大约 650 个 `.rs` 文件。Rust 按 crate 编译，
   改其中任何一个文件，整个 crate 都要重新检查和生成代码，Bevy 的泛型还会在这里大量展开。
3. **链接慢。** Bevy 程序很大，Windows 默认的 MSVC `link.exe` 很慢。
4. **Windows Defender 实时扫描** `target` 里成千上万个文件。
5. **缓存反复作废。** 三个副本各自一份缓存，debug、release、安卓又各是独立缓存，
   来回切换或者手动清掉 `target`，就要全量重编，磁盘占用也越来越大。

## 3. 做了哪些改动

### 3.1 公共配置 `D:\pc-soft\wow-benilla\.cargo\config.toml`

Cargo 会往上层目录找配置并合并，所以三个副本会自动继承，它们自己的文件一个都没改。

- `build.target-dir = "D:/pc-soft/wow-benilla/_target"`：三个副本共用缓存，Bevy 等依赖只编一份。
- `[target.x86_64-pc-windows-msvc] linker = "rust-lld.exe"`：桌面版用 rust-lld 链接，快很多。
  安卓不受影响，仍用 NDK 自己的链接器。
- `[profile.dev] debug = "line-tables-only"`：自己的代码只保留行号，panic 时仍能看到出错行。
- `[profile.dev.package."*"] debug = false`：依赖库不生成调试信息，省磁盘也省链接时间。
- `[profile.play] debug = false`。

项目原本就有的设置（在 `Cargo.toml` 里，没有改）：

- dev profile：依赖库 `opt-level = 3`（不然碰撞计算会卡到不到 1 fps），自己的代码 `opt-level = 1`，开增量编译。
- play profile（`cargo play`）：release 级别优化 + 增量编译 + 关闭 LTO。

### 3.2 一键脚本 `D:\pc-soft\wow-benilla\bn.ps1`

脚本会自动设置这些环境变量：

- `CARGO_TARGET_DIR = D:\pc-soft\wow-benilla\_target`
  （`cargo-apk` 不读上层目录的 `.cargo/config.toml`，只认这个环境变量。）
- 安卓：`ANDROID_HOME` / `ANDROID_SDK_ROOT` = `D:\pc-soft\WoWdot-main\tools\android\sdk`，
  `ANDROID_NDK_HOME` / `ANDROID_NDK_ROOT` = `...\sdk\ndk\28.1.13356709`，
  `JAVA_HOME` = `D:\Program Files\Java\jdk-21.0.11`
- 桌面：`WOW_DATA` 默认 `D:\wow\twmoa_client\Data`，`WOW_HOST` 可选

脚本文件是带 BOM 的 UTF-8。Windows 自带的 PowerShell 5.1 读不带 BOM 的 UTF-8 脚本时会把中文读乱，
以后改脚本要保持这个编码，而且字符串里不要用中文引号“”（PowerShell 会把它们当成引号）。

## 4. 日常命令

```powershell
cd D:\pc-soft\wow-benilla

# 改代码时
.\bn.ps1 check                        # 只查编译错误，约 10 秒
.\bn.ps1 run                          # 编译并启动桌面版（日常调试用这个）
.\bn.ps1 run -WowHost 192.168.2.3     # 指定服务器
.\bn.ps1 test creature_anim           # 只跑 benilla-app 里名字带 creature_anim 的单元测试
.\bn.ps1 play                         # 接近正式版性能，测帧率和手感时用

# 上手机（只在需要真机验证时用）
.\bn.ps1 check-android                # 只查安卓目标的编译错误，不打包
.\bn.ps1 apk                          # 打 debug APK
.\bn.ps1 install                      # 装上次打好的 APK 并启动
.\bn.ps1 apk-run                      # apk + install
.\bn.ps1 log                          # 看手机上这个 App 的 logcat

# 磁盘
.\bn.ps1 size                         # 看缓存占用
.\bn.ps1 trim                         # 删 release 产物、3 天前的增量缓存、各副本里旧的 target
.\bn.ps1 clean                        # 删除整个缓存（下次全量重编，会先问 y/N）

# 正式版（慢，只在要发给别人时用）
.\bn.ps1 release

# Defender 排除（要在“以管理员身份运行”的 PowerShell 里执行）
.\bn.ps1 defender
```

参数：

- `-P twow|main|clone`：选副本，默认 `twow`（`benilla-twow-main`）。例如 `.\bn.ps1 run -P main`。
- `-Data <路径>`：桌面版 `WOW_DATA`。
- `-WowHost <地址>`：桌面版 `WOW_HOST`。
- 如果提示禁止运行脚本：执行一次 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。

相关路径：

- 桌面程序：`D:\pc-soft\wow-benilla\_target\debug\benilla.exe`
- 安卓包：`D:\pc-soft\wow-benilla\_target\debug\apk\benilla.apk`（包名 `com.benilla.twow`）
- 手机上的游戏数据：`/sdcard/Android/media/com.benilla.twow/WOWDATA`
- 手机上的配置和崩溃报告：`/sdcard/Android/media/com.benilla.twow/benilla-config/`
- 安卓工程只在 `benilla-twow-main` 和 `benilla-twow-clone` 里有（`crates/benilla-android`），`benilla-main` 没有。

## 5. 注意事项

- **不要再直接用 `cargo build --release`。** release 是另一套独立缓存，要全量编十几分钟，还要多占十几 GB。
  确实要正式版时用 `.\bn.ps1 release`，用完 `.\bn.ps1 trim` 会把它删掉。
- **打安卓包一定要走脚本。** 直接 `cargo apk build` 不会带 `CARGO_TARGET_DIR`，
  cargo-apk 会去项目自己的 `target` 里找 `.so`，然后报“系统找不到指定的路径 (os error 3)”。
- **缓存路径不要随便改。** cargo-apk 会把缓存路径写进传给 rustc 的参数里，路径一变，安卓版就要全部重编。
- **不要来回切换 feature**（比如有时加 `--no-default-features`），每种组合都会另存一份产物。
- **同时编两个副本时会排队等锁**；`_target\debug\benilla.exe` 是最后一次编译的那个副本。
- **`benilla-main` 第一次编会慢一些**：它自己的 benilla crate 要单独编，但 Bevy 等依赖可以复用。
- **缓存大小（2026-10-12）**：合计约 22.6 GB，其中桌面 dev 约 10.9 GB，安卓约 11.6 GB。
  安卓那份里有一部分是第一次路径没配对时留下的旧产物，Cargo 不会自动删。想回收就执行一次
  `cargo clean --target aarch64-linux-android`（在项目目录里，先设好 `$env:CARGO_TARGET_DIR`），
  代价是下次打 APK 要重编大约 11 分钟。
- **改 UI 的 Lua/XML 不一定要重编。** dev 构建会优先读磁盘上的 `crates/benilla-app/assets/ui`，一般重启客户端就行。
- **项目自带的测试用环境变量**（详见 `docs/CONTRIBUTING.md`）：
  - `WOW_UNATTENDED=1`：自动重连，不停在对话框
  - `WOW_RIG="tauren druid 60 gear:... at:ThunderBluff"`：在 vmangos 上自动找到或创建角色、套装备、传送
  - `WOW_PROBE_CHAT="<命令>"`：自动发一条 GM 命令
  - `WOW_STOCK_UI=1`：只用原版界面启动

## 6. benilla 和 wowgd 怎么选（评估结论）

| | benilla（Rust + Bevy） | wowgd（Godot） |
|---|---|---|
| 还原官方程度 | 高。动画、受击、溅血、法术视觉都有专门模块：`creature_anim/impact.rs`、`driver/wound.rs`、`blood.rs`、`spell_visual.rs` | 打击感、动画、技能还没对齐 |
| 改完到看到效果 | 现在约 20 秒 | F5 秒开，有编辑器工具 |
| 安卓 | 能编，但项目主要按桌面开发，触屏 UI 要自己做 | 已有 `mobile_controls`、`mobile_hud_shell`、移动端性能面板 |
| 后续工作量 | 修 bug、加功能 | 要把 benilla 那套逆向还原出来的逻辑用 GDScript 重写，工作量很大 |

- **看重手感和还原度：选 benilla。** 编译慢的问题已经解决，wowgd 要追上它的还原度是几个月级别的移植工作。
- **最终做安卓手游、要自己的触屏 UI 和编辑工具：wowgd 有底子。** 可以把 benilla 当“规格说明书”：
  它的注释写得很细，很多地方直接注明了 1.12 原版的行为，可以按模块（打击感、受击动画等）翻译成 GDScript，一块一块对齐。
