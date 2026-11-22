# 上传到 GitHub

两条路，选一条。**推荐 A（网页创建 + token 推送）**，最不容易出错。

---

## 第一步：在 GitHub 建空仓库

1. 打开 <https://github.com/new>
2. 填：
   - **Repository name**: `unitycn`
   - **Description**（可选）：`在中国大陆获取 Unity 6/7 编辑器与构建模块，无需 VPN`
   - **Visibility**: 选 `Public`（想私有就选 Private）
3. **下面三个勾选框全部不要勾** —— 尤其不要勾 "Add a README file"、".gitignore"、"license"。
   你已经有了这些文件，勾了会产生冲突，推送时会报 rejected。
4. 点 **Create repository**

建完页面会显示一个空仓库，上面有 HTTPS 地址，形如：

```
https://github.com/你的用户名/unitycn.git
```

---

## 第二步：生成 Personal Access Token

GitHub 从 2021 年起不接受账号密码推送，必须用 token。

1. 打开 <https://github.com/settings/tokens>
2. 选 **Tokens (classic)** → 右上角 **Generate new token (classic)**
3. 填：
   - **Note**: `unitycn push`
   - **Expiration**: 30 days（够用了，过期再生成）
   - **Scopes**: 只勾 **`repo`**（整个大类勾上就行）
4. 点 **Generate token**
5. **立刻复制那串 `ghp_xxxxxxxx`** —— 离开页面后就再也看不到了

> 想用 fine-grained token 也行，但需要手动选仓库并给 `Contents: Read and write` 权限，
> 比 classic 麻烦。第一次用 classic 就够。

---

## 第三步：推送

在仓库根目录（`...\unity7`）执行：

```powershell
.\push_github.ps1 -Repo https://github.com/你的用户名/unitycn.git `
                  -Name "你的名字" -Email "你的GitHub邮箱"
```

脚本会依次做：

1. **自检** —— 跑测试、确认没有敏感文件混进去
2. **重写提交身份** —— 把占位的 `unitycn@localhost` 换成你的名字和邮箱
3. **填入仓库地址** —— 替换 `pyproject.toml` 里的 `OWNER/unitycn` 占位符
4. **加远端并推送**

推送时会**弹窗要用户名和密码**：

- 用户名：你的 GitHub 用户名
- 密码：**粘贴那个 `ghp_...` token**（不是账号密码）

---

## 如果不想跑脚本，手敲这四行

```powershell
cd "C:\Users\Administrator\Documents\deepseek-harness\default-workspace\unity7"

# 1) 改成你自己的身份（否则提交记录里是 unitycn@localhost）
git config user.name  "你的名字"
git config user.email "你的GitHub邮箱"

# 2) 加远端
git remote add origin https://github.com/你的用户名/unitycn.git

# 3) 推送（回车后输入用户名 + token）
git push -u origin main
```

历史里那 4 个提交的作者仍然是 `unitycn@localhost`，不影响使用，只是头像显示不出来。
想彻底改掉，用脚本里的 `-Name`/`-Email` 参数，它会重写历史。

---

## 会推上去什么

```
36 个文件，约 4000 行

.github/workflows/ci.yml   CI（3 平台 × 3 个 Python 版本）
.gitignore                 已排除代理池与安装包
CONTRIBUTING.md
LICENSE                    MIT
PACKAGE.md
README.md                  主文档
install_offline.ps1        不依赖 pip 的安装脚本
push_github.ps1            本脚本
pyproject.toml
tests/test_units.py        23 个测试
unitycn/                   包源码 9 个模块
archive/                   16 个早期探索脚本
docs/FAQ.md
docs/MEASUREMENTS.md       实测基线
```

**不会推上去**（`.gitignore` 已排除，脚本还会二次检查）：

- `pool.txt` 和任何代理列表 —— 免费代理寿命以小时计，传上去第二天全是死节点
- `UnitySetup64-*.exe`（3.5 GB）、`modules/` 里的 1.16 GB 组件包
- `.cache/`

---

## 常见问题

**报 `rejected - non-fast-forward`**

建仓库时勾了 README/LICENSE。删掉那个仓库重建，或者：

```powershell
git pull --rebase origin main
git push -u origin main
```

**报 `Authentication failed`**

- 密码栏填的是账号密码 → 换成 token
- token 没勾 `repo` 权限 → 重新生成
- token 复制时带了空格 → 重新复制

**报 `remote origin already exists`**

```powershell
git remote set-url origin https://github.com/你的用户名/unitycn.git
```

**推送卡住不动**

多半是卡在凭据弹窗背后。关掉所有 git 相关窗口重试；
或者先把凭据存起来：

```powershell
git config --global credential.helper manager
```

**想改仓库名或转私有**

在 GitHub 仓库页 **Settings** 里改，地址会自动跟着变，本地执行
`git remote set-url origin <新地址>` 即可。

---

## 上传之后建议做的三件事

1. **加 Topics** —— 仓库页右上角齿轮，填 `unity` `unity3d` `china` `proxy` `download`，
   方便别人搜到。

2. **确认 CI 跑绿** —— 打开仓库的 **Actions** 标签。
   `.github/workflows/ci.yml` 会在 Windows/Ubuntu/macOS 上跑 3 个 Python 版本。
   首次可能因为 `metadata` job 联网失败变黄，那个 job 设了 `continue-on-error`，不影响。

3. **把 README 顶部的 `OWNER` 占位检查一遍** —— 脚本会自动替换，手敲的话记得改：

   ```powershell
   (Get-Content README.md -Raw) -replace 'OWNER/unitycn', '你的用户名/unitycn' |
       Set-Content README.md -NoNewline
   ```
