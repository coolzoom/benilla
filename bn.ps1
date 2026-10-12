<#
benilla 日常开发脚本（放在 D:\pc-soft\wow-benilla 下，三个副本共用）

  .\bn.ps1 check                只查编译错误，不生成 exe（最快）
  .\bn.ps1 run                  dev 版编译并启动桌面客户端（日常调试用这个）
  .\bn.ps1 play                 接近 release 性能 + 增量编译（测帧率/手感时用）
  .\bn.ps1 test creature_anim   只跑 benilla-app 里名字含 creature_anim 的单元测试
  .\bn.ps1 check-android        只查安卓目标的编译错误，不打包
  .\bn.ps1 apk                  打 debug APK（不签 release，快）
  .\bn.ps1 install              把上次打好的 APK 装到手机并启动
  .\bn.ps1 apk-run              apk + install
  .\bn.ps1 log                  看手机上这个 App 的 logcat
  .\bn.ps1 release              正式版 exe（慢，只在要发给别人时用）
  .\bn.ps1 size                 看编译缓存占多少空间
  .\bn.ps1 trim                 清掉 release 产物、过期增量缓存、旧的 target 目录
  .\bn.ps1 clean                删掉整个编译缓存（下次全量重编）
  .\bn.ps1 defender             把编译目录加入 Defender 排除（需要管理员 PowerShell）

  -P twow|main|clone   选副本：benilla-twow-main（默认）/ benilla-main / benilla-twow-clone
  -Data <路径>          桌面版 WOW_DATA，默认 D:\wow\twmoa_client\Data
  -WowHost <地址>       桌面版 WOW_HOST，例如 192.168.2.3
#>
param(
    [Parameter(Position = 0)][string]$Cmd = 'help',
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rest = @(),
    [ValidateSet('twow', 'main', 'clone')][string]$P = 'twow',
    [string]$Data = 'D:\wow\twmoa_client\Data',
    [string]$WowHost = ''
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Dir = Join-Path $Root (@{ twow = 'benilla-twow-main'; main = 'benilla-main'; clone = 'benilla-twow-clone' }[$P])
$Target = Join-Path $Root '_target'
$Sdk = 'D:\pc-soft\WoWdot-main\tools\android\sdk'
$Ndk = Join-Path $Sdk 'ndk\28.1.13356709'
$Adb = Join-Path $Sdk 'platform-tools\adb.exe'
$Pkg = 'com.benilla.twow'
$Apk = Join-Path $Target 'debug\apk\benilla.apk'
# cargo-apk 不读上层目录的 .cargo/config.toml，只认这个环境变量
$env:CARGO_TARGET_DIR = $Target

function Invoke-Cargo {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Push-Location $Dir
    try { & cargo @args } finally { Pop-Location }
    $code = $LASTEXITCODE
    Write-Host ("[bn] cargo {0}  用时 {1:mm\:ss}" -f ($args -join ' '), $sw.Elapsed) -ForegroundColor Cyan
    if ($code -ne 0) { exit $code }
}

function Use-Android {
    $env:ANDROID_HOME = $Sdk
    $env:ANDROID_SDK_ROOT = $Sdk
    $env:ANDROID_NDK_HOME = $Ndk
    $env:ANDROID_NDK_ROOT = $Ndk
    if (-not $env:JAVA_HOME) { $env:JAVA_HOME = 'D:\Program Files\Java\jdk-21.0.11' }
    if (-not (Test-Path (Join-Path $Dir 'crates\benilla-android'))) {
        throw "$Dir 没有 benilla-android，安卓只能用 -P twow 或 -P clone"
    }
}

function Use-Desktop {
    $env:WOW_DATA = $Data
    if ($WowHost) { $env:WOW_HOST = $WowHost }
}

function Get-SizeGB([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return 0 }
    $sum = (Get-ChildItem -LiteralPath $Path -Recurse -File -Force -ErrorAction SilentlyContinue |
        Measure-Object Length -Sum).Sum
    [math]::Round($sum / 1GB, 2)
}

function Show-Size {
    Write-Host ("_target 合计 {0} GB" -f (Get-SizeGB $Target))
    if (Test-Path $Target) {
        Get-ChildItem -LiteralPath $Target -Directory | ForEach-Object {
            Write-Host ("  {0,-26} {1} GB" -f $_.Name, (Get-SizeGB $_.FullName))
        }
    }
    foreach ($d in 'benilla-main', 'benilla-twow-main', 'benilla-twow-clone') {
        $t = Join-Path $Root "$d\target"
        $gb = Get-SizeGB $t
        if ($gb -gt 0) { Write-Host ("  旧缓存 {0}\target  {1} GB（可以 trim 掉）" -f $d, $gb) -ForegroundColor Yellow }
    }
}

function Install-Apk {
    if (-not (Test-Path $Apk)) { throw "没有找到 $Apk，先运行 .\bn.ps1 apk" }
    & $Adb install -r $Apk
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Adb shell am force-stop $Pkg
    & $Adb shell monkey -p $Pkg -c android.intent.category.LAUNCHER 1 | Out-Null
    Write-Host "[bn] 已安装并启动 $Pkg" -ForegroundColor Cyan
}

switch ($Cmd) {
    'check' { Invoke-Cargo check -p benilla @Rest }
    'run' { Use-Desktop; Invoke-Cargo run -p benilla @Rest }
    'play' { Use-Desktop; Invoke-Cargo run --profile play -p benilla @Rest }
    'test' { Invoke-Cargo test -p benilla-app --lib @Rest }
    'check-android' { Use-Android; Invoke-Cargo check -p benilla-android --target aarch64-linux-android @Rest }
    'apk' { Use-Android; Invoke-Cargo apk build -p benilla-android @Rest; Write-Host "[bn] APK: $Apk" -ForegroundColor Cyan }
    'install' { Install-Apk }
    'apk-run' { Use-Android; Invoke-Cargo apk build -p benilla-android @Rest; Install-Apk }
    'log' {
        $procId = (& $Adb shell pidof -s $Pkg).Trim()
        if (-not $procId) { throw "$Pkg 没在运行" }
        & $Adb logcat --pid=$procId
    }
    'release' { Invoke-Cargo build --release -p benilla @Rest }
    'size' { Show-Size }
    'trim' {
        $before = Get-SizeGB $Target
        foreach ($sub in 'release', 'ship', 'aarch64-linux-android\release') {
            $subDir = Join-Path $Target $sub
            if (Test-Path $subDir) { Write-Host "删除 $subDir"; Remove-Item -LiteralPath $subDir -Recurse -Force }
        }
        $cutoff = (Get-Date).AddDays(-3)
        Get-ChildItem -LiteralPath $Target -Recurse -Directory -Filter incremental -ErrorAction SilentlyContinue |
            ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -Directory } |
            Where-Object { $_.LastWriteTime -lt $cutoff } |
            ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
        foreach ($d in 'benilla-main', 'benilla-twow-main', 'benilla-twow-clone') {
            $t = Join-Path $Root "$d\target"
            if (Test-Path $t) {
                Get-ChildItem -LiteralPath $t -Force | Where-Object { $_.Name -notin '.rustc_info.json', 'CACHEDIR.TAG' } |
                    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
            }
        }
        Write-Host ("[bn] trim: {0} GB -> {1} GB" -f $before, (Get-SizeGB $Target)) -ForegroundColor Cyan
    }
    'clean' {
        if ((Read-Host "删除整个 $Target ? 下次要全量重编 (y/N)") -eq 'y') { Remove-Item -LiteralPath $Target -Recurse -Force }
    }
    'defender' {
        $paths = @($Target, "$env:USERPROFILE\.cargo", "$env:USERPROFILE\.rustup")
        $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)
        if (-not $admin) { throw "需要用 [以管理员身份运行] 的 PowerShell 执行 .\bn.ps1 defender" }
        foreach ($path in $paths) { Add-MpPreference -ExclusionPath $path; Write-Host "已排除 $path" }
        Add-MpPreference -ExclusionProcess 'cargo.exe', 'rustc.exe', 'rust-lld.exe'
    }
    default { Get-Content -LiteralPath $PSCommandPath -Encoding UTF8 -TotalCount 21 | Select-Object -Skip 1 | Out-Host }
}
