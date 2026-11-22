# 把已下载的 SDK/NDK/JDK 铺到 Unity 期望的路径
$ErrorActionPreference = 'Continue'
$M   = "C:\Users\Administrator\Documents\deepseek-harness\default-workspace\unity7\modules"
$AP  = "D:\Unity\Editors\7000.0.0a20\Editor\Data\PlaybackEngines\AndroidPlayer"
$SDK = "$AP\SDK"
$NDK = "$AP\NDK"
$JDK = "$AP\OpenJDK"
$7z  = "C:\Program Files\7-Zip\7z.exe"

function Unzip($zip, $dest, $label) {
    $resolved = (Get-ChildItem $zip -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $resolved) { Write-Host "  SKIP (missing): $label"; return }
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Write-Host "  extracting $label -> $dest"
    & $7z x $resolved.FullName "-o$dest" -y -bso0 -bsp0 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host "    !! 7z exit $LASTEXITCODE" }
}

function Flatten($dest, $innerName) {
    $inner = Join-Path $dest $innerName
    if (Test-Path $inner) {
        Get-ChildItem $inner | Move-Item -Destination $dest -Force
        Remove-Item $inner -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "    flattened $innerName"
    }
}

Write-Host "=== NDK ==="
Unzip "$M\android-ndk-r27c-windows.zip" $NDK "NDK r27c"
Flatten $NDK "android-ndk-r27c"

Write-Host "=== OpenJDK ==="
Unzip "$M\jdk17.0.21-9_*.zip" $JDK "OpenJDK 17.0.21"

Write-Host "=== SDK platform-tools ==="
Unzip "$M\platform-tools_r37.0.1-win.zip" "$SDK\platform-tools" "platform-tools"
Flatten "$SDK\platform-tools" "platform-tools"

Write-Host "=== SDK build-tools (android-16 -> 36.0.0) ==="
Unzip "$M\build-tools_r36_windows.zip" "$SDK\_bt_tmp" "build-tools"
if (Test-Path "$SDK\_bt_tmp\android-16") {
    New-Item -ItemType Directory -Force -Path "$SDK\build-tools" | Out-Null
    Move-Item "$SDK\_bt_tmp\android-16" "$SDK\build-tools\36.0.0" -Force
    Remove-Item "$SDK\_bt_tmp" -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "    android-16 -> build-tools\36.0.0"
}

Write-Host "=== SDK platforms ==="
$plats = @()
$plats += ,@('platform-34-ext7_r02.zip','android-34')
$plats += ,@('platform-36_r02.zip','android-36')
$plats += ,@('platform-37.0_r02.zip','android-37.0')
foreach ($p in $plats) {
    $dest = "$SDK\platforms\$($p[1])"
    Unzip "$M\$($p[0])" $dest "$($p[1])"
    Flatten $dest $p[1]
}

Write-Host "=== SDK cmake ==="
Unzip "$M\cmake-3.22.1-windows.zip" "$SDK\cmake\3.22.1" "CMake 3.22.1"

Write-Host "=== SDK cmdline-tools ==="
Unzip "$M\commandlinetools-win-15641748_latest.zip" "$SDK\cmdline-tools\latest" "cmdline-tools"
Flatten "$SDK\cmdline-tools\latest" "cmdline-tools"

Write-Host ""
Write-Host "=== verify ==="
$checks = @()
$checks += ,@("NDK clang",       "$NDK\toolchains\llvm\prebuilt\windows-x86_64\bin\clang.exe")
$checks += ,@("NDK source.props","$NDK\source.properties")
$checks += ,@("JDK java.exe",    "$JDK\bin\java.exe")
$checks += ,@("adb.exe",         "$SDK\platform-tools\adb.exe")
$checks += ,@("aapt2",           "$SDK\build-tools\36.0.0\aapt2.exe")
$checks += ,@("android-34 jar",  "$SDK\platforms\android-34\android.jar")
$checks += ,@("android-36 jar",  "$SDK\platforms\android-36\android.jar")
$checks += ,@("android-37 jar",  "$SDK\platforms\android-37.0\android.jar")
$checks += ,@("cmake.exe",       "$SDK\cmake\3.22.1\bin\cmake.exe")
$checks += ,@("sdkmanager",      "$SDK\cmdline-tools\latest\bin\sdkmanager.bat")
foreach ($c in $checks) {
    $s = if (Test-Path $c[1]) { "OK" } else { "MISSING" }
    "  {0,-18} {1}" -f $c[0], $s
}
