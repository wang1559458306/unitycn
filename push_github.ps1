# 一键推送到 GitHub
#
# 用法（在仓库根目录执行）:
#   .\push_github.ps1 -Repo https://github.com/你的用户名/unitycn.git
#
# 会依次做：修正提交身份 → 替换占位链接 → 加远端 → 推送
# Token 不会写进任何文件；首次推送时 git 会弹出窗口让你输入。

param(
    [Parameter(Mandatory = $true)]
    [string]$Repo,

    # 你的 GitHub 用户名与邮箱（会写进提交记录）
    [string]$Name  = "",
    [string]$Email = ""
)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

if ($Repo -notmatch '^https://github\.com/([^/]+)/([^/]+?)(\.git)?$') {
    throw "仓库地址格式不对。应为 https://github.com/<用户名>/<仓库名>.git"
}
$owner = $Matches[1]
$reponame = $Matches[2]

Write-Host "仓库   : $owner/$reponame"
Write-Host "分支   : main"

# 推送前自检
Write-Host "`n[自检]"
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
    & python -c "import unitycn; print('  import OK', unitycn.__version__)"
    & python -m unittest discover -s tests 2>&1 | Select-Object -Last 2 | ForEach-Object { "  $_" }
} else {
    Write-Host "  跳过（未找到 python）"
}

# 敏感文件绝不能推上去
$bad = git ls-files | Select-String -Pattern '(^|/)(pool.*\.txt|.*\.exe|modules/|\.cache/)'
if ($bad) {
    Write-Host "`n!! 检测到不该入库的文件，已中止：" -ForegroundColor Red
    $bad | ForEach-Object { Write-Host "   $_" }
    exit 1
}
Write-Host "  敏感文件检查通过（无代理池 / 无安装包）"

# 修正提交身份
if ($Name -and $Email) {
    Write-Host "`n[重写提交身份] $Name <$Email>"
    $env:GIT_AUTHOR_NAME = $Name;   $env:GIT_AUTHOR_EMAIL = $Email
    $env:GIT_COMMITTER_NAME = $Name; $env:GIT_COMMITTER_EMAIL = $Email
    git config user.name $Name
    git config user.email $Email
    $filter = @'
case "$GIT_COMMITTER_NAME" in
  unitycn) export GIT_COMMITTER_NAME="__N__";  export GIT_COMMITTER_EMAIL="__E__";;
esac
case "$GIT_AUTHOR_NAME" in
  unitycn) export GIT_AUTHOR_NAME="__N__";  export GIT_AUTHOR_EMAIL="__E__";;
esac
'@ -replace '__N__', $Name -replace '__E__', $Email
    $filter | Out-File -FilePath .git-identity-filter -Encoding ascii
    $env:FILTER_BRANCH_SQUELCH_WARNING = '1'
    git filter-branch -f --env-filter "bash .git-identity-filter" main 2>&1 |
        Select-Object -Last 2
    Remove-Item .git-identity-filter -Force
} else {
    Write-Host "`n[提示] 未提供 -Name/-Email，保留现有提交身份（unitycn@localhost）"
    Write-Host "       想换成你自己的，重跑并加上：-Name 你的名字 -Email 你的邮箱"
}

# 替换 pyproject 里的占位链接
Write-Host "`n[更新链接]"
$p = "pyproject.toml"
$c = Get-Content $p -Raw
$c = $c -replace 'OWNER/unitycn', "$owner/$reponame"
[System.IO.File]::WriteAllText((Resolve-Path $p), $c, (New-Object System.Text.UTF8Encoding($false)))
git add pyproject.toml 2>&1 | Out-Null
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git -c core.autocrlf=false commit -q -m "chore: 填入实际仓库地址"
    Write-Host "  已提交链接更新"
} else {
    Write-Host "  无需更新"
}

# 加远端并推送
Write-Host "`n[推送]"
$existing = git remote get-url origin 2>$null
if ($existing) {
    git remote set-url origin $Repo
    Write-Host "  已更新 origin: $Repo"
} else {
    git remote add origin $Repo
    Write-Host "  已添加 origin: $Repo"
}

git push -u origin main

Write-Host "`n完成。" -ForegroundColor Green
Write-Host "仓库地址: https://github.com/$owner/$reponame"
