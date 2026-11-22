# 离线安装 unitycn —— 不依赖 pip / 不需要联网
#
# 用途：受限网络里 pip 拉不到 setuptools 时的兜底方案。
# 做法：把包目录放进 site-packages，并在 Scripts 里生成一个 unitycn.cmd 转发器。
#
#   .\install_offline.ps1              安装到当前用户
#   .\install_offline.ps1 -Uninstall   卸载

param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pkg  = Join-Path $here 'unitycn'

if (-not (Test-Path $pkg)) { throw "找不到 unitycn 包目录：$pkg" }

# 选一个用户级 site-packages（不需要管理员）
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { throw "PATH 里没有 python" }

$site = & $python -c "import site; print(site.getusersitepackages())" 2>$null
if (-not $site) { throw "无法确定 site-packages 路径" }
$target = Join-Path $site 'unitycn'

$scripts = & $python -c "import sysconfig; print(sysconfig.get_path('scripts'))" 2>$null
$cmdFile = Join-Path $scripts 'unitycn.cmd'

if ($Uninstall) {
    if (Test-Path $target)  { Remove-Item $target -Recurse -Force; Write-Host "已移除 $target" }
    if (Test-Path $cmdFile) { Remove-Item $cmdFile -Force;          Write-Host "已移除 $cmdFile" }
    exit 0
}

Write-Host "Python : $python"
Write-Host "目标   : $target"
Write-Host "入口   : $cmdFile"

# 复制包（覆盖安装）
if (Test-Path $target) { Remove-Item $target -Recurse -Force }
Copy-Item $pkg $target -Recurse -Force
Get-ChildItem $target -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# 生成 .cmd 转发器（用 -m 调用，不依赖 console_scripts 生成机制）
New-Item -ItemType Directory -Force -Path $scripts | Out-Null
$cmd = "@echo off`r`n`"$python`" -m unitycn %*`r`n"
Set-Content -Path $cmdFile -Value $cmd -Encoding ASCII -NoNewline

# 验证
Write-Host ""
Write-Host "验证："
& $python -c "import unitycn; print('  import OK', unitycn.__version__)"
& $python -m unitycn --help 2>&1 | Select-Object -First 2 | ForEach-Object { "  $_" }

Write-Host ""
Write-Host "完成。若 unitycn 命令不在 PATH，直接用："
Write-Host "  python -m unitycn <子命令>"
