# unitycn

**在中国大陆获取 Unity 6 / 7 编辑器与构建模块 —— 无需 VPN，用公开 API + 分片并发。**

> 本文所有结论均为实测（2026-11，上海电信家庭宽带，出口 IP 段 `112.x`）。
> 不猜测、不转述、不引用未验证的说法。

---

## 它解决什么

你打开 Unity Hub，选了 7000.0.0a20，点安装 —— 进度条停在 0%，最后提示
“验证失败 / Validation Failed”。换网络、挂代理、重装 Hub，都没用。

**这不是网络慢，是 Hub 拿到一个指向不存在文件的地址。**

unitycn 绕开 Hub 的下载器：直接从 Unity 公开 API 拿直链，用分片并发下载，
下载完用官方给的 MD5 校验，再命令行装进 Hub 能识别的目录。

```bash
pip install -e .

unitycn doctor                              # 先看环境与连通性
unitycn versions --alpha                    # 查最新 alpha 版本与直链
unitycn fetch --version 7000.0.0a20         # 下编辑器（3.5 GB）
unitycn modules --version 7000.0.0a20 --alpha   # 看有哪些模块
unitycn fetchm --version 7000.0.0a20 --alpha --only android,windows-il2cpp
```

需要代理池时：

```bash
unitycn pool --out pool.txt                 # 抓源+探测+测速，约 5 分钟
unitycn fetch --version 7000.0.0a20 --pool pool.txt
```

---

## 封锁到底是怎么实现的

### 一、302 到一个空仓库

```
$ curl -I https://download.unity3d.com/download_unity/f4e960bd2f88/Windows64EditorInstaller/UnitySetup64-7000.0.0a20.exe
HTTP/1.1 302 Moved Temporarily
Server: AkamaiGHost
Location: https://download.unitychina.cn/download_unity/f4e960bd2f88/Windows64EditorInstaller/UnitySetup64-7000.0.0a20.exe
```

跟过去看看：

```
$ curl -I https://download.unitychina.cn/download_unity/f4e960bd2f88/...exe
HTTP/1.1 404 Not Found
Server: AliyunOSS
<Error><Code>NoSuchKey</Code><Message>The specified key does not exist.</Message>
```

`download_unity/` 这个前缀下**一个国际版编辑器都没有**。用三个真实存在的版本
（`7000.0.0a20`、`6000.0.85f2`、`2022.3.62f3`）验证，全部 404：

```
$ curl -o /dev/null -w "%{http_code}" https://download.unitychina.cn/download_unity/
404
```

团结引擎（Tuanjie）在**另一条独立路径** `download.tuanjie.cn/download_tuanjie/`，
版本号形如 `2022.3.62t18`（后缀 `t`），与国际版的 `f`/`a`/`b` 完全不互通。

### 二、区域判定只看源 IP

试过这些全部无效：

| 伪装手段 | 结果 |
|---|---|
| `X-Forwarded-For: 8.8.8.8` | 仍然 302 |
| `True-Client-IP: 8.8.8.8` | 仍然 302 |
| `CF-Connecting-IP: 8.8.8.8` | 仍然 302 |
| `X-Real-IP: 8.8.8.8` | 仍然 302 |
| `Accept-Language: en-US` | 仍然 302 |
| `User-Agent: UnityPackageManager` | 仍然 302 |
| `?x=1` / `?download=1` | 仍然 302 |
| 强制解析到海外 Akamai 节点（`--resolve`） | 仍然 302 |

判定发生在**接入侧**，不在 CDN 节点侧。改 hosts、改 DNS 都没用。

### 三、但元数据不设防

这是最关键的一条：**Unity 的 API 在中国大陆可直连。**

| 端点 | 用途 | 国内直连 |
|---|---|---|
| `services.api.unity.com/unity/editor/release/v1/releases` | 版本、直链、字节数、MD5 | ✅ |
| `public-cdn.cloud.unity3d.com/hub/prod/releases-win32.json` | 模块直链、checksum | ✅ |

**所以：查什么版本、哪个链接、多大、校验值是多少 —— 全都不需要翻墙。
只有文件本体所在的 `download.unity3d.com` 需要。**

---

## 各来源的真实可达性

这张表能省掉大量无用功：

| 来源 | 主机 | 国内直连 | 实测速度 |
|---|---|---|---|
| **Google**（Android SDK/NDK） | `dl.google.com` | ✅ | **9–15 MB/s** |
| **Microsoft**（Visual Studio） | `aka.ms` → `download.visualstudio.microsoft.com` | ✅ | 0.4 MB/s |
| **Unity**（编辑器、模块、OpenJDK） | `download.unity3d.com` | ❌ 302 → 404 | 走代理 0.7–1.7 MB/s |

**结论：Android SDK & NDK 那 1.16 GB 完全不需要代理，直连比翻墙快一个数量级。**
只有 Unity 自己的文件要走代理。

`unitycn` 对每个 URL 自动判断：先直连探 64 字节，首字节是 `4D5A`（PE）/ `504B`（ZIP）
就走直连多线程，否则自动挂代理池。

---

## 为什么必须高并发

瓶颈**不是总带宽，是单连接限速**。同一个 Unity CDN 文件，同一个代理：

| 并发线程 | 吞吐 |
|---|---|
| 1 | 0.74 MB/s |
| 4 | 1.59 MB/s |
| 16 | 2.54 MB/s |
| 32 | 3.68 MB/s |
| **96** | **6.46 MB/s** |
| 128 | 4.57 MB/s（开始回落） |

所以：**2MB 小分片 + 几十上百条并发连接**。分片越小调度越均匀，但元数据开销越大，
2MB 是实测的平衡点。

---

## 代理池

### 用它是为了什么

免费公开代理**单连接很慢**（多数 0.01–0.1 MB/s），但**可以开很多条**。
96 条并发叠上去能到 4–6 MB/s，够拉 3–8 GB 的安装包。

实话实说：这不是高速通道。2026-11 那次实测，6000 多个候选里存活约 240 个，
其中**只有 1–5 个超过 0.5 MB/s**。能跑通，但别指望 50 MB/s。

**如果你手上已有可用的代理工具（Clash / V2Ray / 公司 HTTP 代理），
往池文件里加一行就够了，比抓代理强得多：**

```
http://127.0.0.1:7890	99.0
```

### 抓取

`unitycn pool` 做三件事：

1. **抓源**：16 个源，分两类 ——
   - **API 型（5 个）**：`api.openproxylist.xyz`、`proxyspace.pro`、`proxylist.geonode.com`。
     **不经过 GitHub**，在内网/校园网封 `raw.githubusercontent.com` 的环境里是唯一可用的源。
   - **GitHub 列表（11 个）**：经 `ghproxy.net` / `jsdelivr` 镜像回退。
2. **探测存活**：每个候选发一个 1KB 的 Range 请求，校验首字节。
3. **测速**：拉 4MB，按 MB/s 排序。

实测规模（2026-11-22）：**22206 个去重候选 → 466 存活 → 151 测速有效**，耗时 8.8 分钟。

### 两个必须遵守的探测纪律

这两条都是踩坑换来的，写进代码注释了：

**纪律一：必须打 offset 0 的段。**
Unity CDN 对文件**中间偏移**经常返回超时或空响应（实测 offset `100000000` 直接 `curl: 000`），
只有头段和尾段稳定返回 206。用中间偏移探测会把大量可用代理误判成死代理 ——
我们复现过：7529 个候选只命中 5 个。

**纪律二：必须校验响应首字节。**
只看状态码会被透明代理、验证码页、运营商劫持页骗过（它们同样回 200）。
Windows 安装包是 PE，前两字节 `4D 5A`；zip 是 `50 4B`。对不上就是假的。

### 不要用元数据预筛（实测反直觉）

`geonode` 这类 API 会返回 `upTime`、`anonymityLevel`、`country`、`lastChecked`，
看起来非常适合先筛一遍再探测。**实测证明没有预测力：**

| 组 | 命中率 |
|---|---|
| upTime top 60 | 1.7% |
| upTime >= 95 前 200 | 2.0% |
| elite 前 120 | **0.8%** |
| 随机 120（基线） | 0.0% |

socks5 那边 elite 组和随机组完全一样（都是 2.5%）。

原因：它们的 `upTime` 测的是**访问普通网站**，而我们要穿的是 Unity 的 Akamai CDN。
一个能上 Google 的代理，未必能过 Unity 的区域节点。

**所以本项目只取 `ip:port`，不按元数据预筛。** 这一条写进了 `sources.py` 的注释。

### 为什么不用 `proxy_pool` / `async-proxy-pool` 那类现成服务

它们的设计目标是**给爬虫用**：维护常驻池 + 用 `httpbin.org/ip` 判活 + 对外给 API。

问题在于**校验目标不匹配**：按它们的标准"存活 100 个"的池，对我们真实可用数
还是个位数。**等于用没校准过的尺子量长度。**

所以本项目反过来：**不维护常驻服务，现用现测、用完即弃。** 每次多花 3–9 分钟，
换来不会拿到"看起来有 500 个其实全是废的"池。

真要用常驻服务也行，但拿到的池必须用 `unitycn.probe.probe_many()`
按 Unity CDN 重新判活 —— 见 `docs/MEASUREMENTS.md` 第 9.6 节。

### 池的调度策略

- **在速度前 40% 里随机挑**。永远挑最快的 → 该出口很快被限流；完全均匀随机 → 被龟速节点拖垮。
- **失败降权而非立即淘汰**。免费代理是间歇性的，连续失败 4 次才认定死亡；全池降权时整体重置。
- **现用现建，不要提交到仓库**。免费代理寿命以小时计，提交了第二天全是死节点。

---

## 离线安装模块

编辑器装好只是第一步。加 Android 模块时 Hub 还是会失败，因为模块 `.exe`
走同一个被拦的 CDN。`unitycn fetchm` 把模块下下来之后：

```powershell
# 关键：安装器路径不要太长、不要带空格，否则 NSIS 会报
#   "Error writing temporary file. Make sure your temp folder is valid."
# 复制到短路径再运行，我们实测这一步是决定性的
Copy-Item .\UnitySetup64-7000.0.0a20.exe D:\u7.exe
D:\u7.exe /S /D=D:\Unity\Editors\7000.0.0a20
Copy-Item .\UnitySetup-Android-Support-for-Editor-7000.0.0a20.exe D:\u7a.exe
D:\u7a.exe /S /D=D:\Unity\Editors\7000.0.0a20
```

> `/S` 静默，`/D=` 指定安装根目录（**必须是最后一个参数，且不加引号**）。
> 装完 `Unity.exe` 在 `<根目录>\Editor\Unity.exe`。
> 官方文档：<https://docs.unity.com/en-us/engine/6000.0/manual/get-started/install-and-upgrade/getting-started-installing-unity/installing-unity>

### Android 组件的手工铺法

模块 `.exe` 只装 PlaybackEngine，**SDK / NDK / OpenJDK 要自己解压**。
`unitycn fetchm --only android,...` 会把它们都下下来。

目标路径（`<AP>` = `<Editor>\Data\PlaybackEngines\AndroidPlayer`）：

| 压缩包 | 解压到 | 注意 |
|---|---|---|
| `android-ndk-r27c-windows.zip` | `<AP>\NDK` | 顶层是 `android-ndk-r27c/`，需上移一层 |
| `jdk17...zip` | `<AP>\OpenJDK` | 顶层直接是 `bin/`，不用上移 |
| `platform-tools_r37.0.1-win.zip` | `<AP>\SDK\platform-tools` | 顶层是 `platform-tools/`，需上移 |
| `build-tools_r36_windows.zip` | `<AP>\SDK\build-tools\36.0.0` | **顶层叫 `android-16`，必须改名 `36.0.0`** |
| `platform-36_r02.zip` | `<AP>\SDK\platforms\android-36` | 需上移 |
| `platform-37.0_r02.zip` | `<AP>\SDK\platforms\android-37.0` | **注意是 `37.0` 不是 `37`** |
| `cmake-3.22.1-windows.zip` | `<AP>\SDK\cmake\3.22.1` | 顶层直接是 `bin/`，**不要**再套一层 |
| `commandlinetools-...zip` | `<AP>\SDK\cmdline-tools\latest` | 需上移 |

> 顺手记一个坑：官方清单里 `android-sdk-tools` 那条指向的 zip 只有 **166 字节**，
> 里面是一个空的 `tools/u` 目录。真正的 SDK 内容就是上面那 8 个 Google 组件。

一条命令验证铺得对不对：

```powershell
$AP = "D:\Unity\Editors\7000.0.0a20\Editor\Data\PlaybackEngines\AndroidPlayer"
& "$AP\OpenJDK\bin\java.exe" -version
& "$AP\SDK\platform-tools\adb.exe" version
Get-Content "$AP\NDK\source.properties"
& "$AP\SDK\cmdline-tools\latest\bin\sdkmanager.bat" --sdk_root="$AP\SDK" --list_installed
```

`install_android_sdk.ps1` 把上面的解压+上移+改名全做了，含 10 项校验。

---

## 这个项目遇到的坑（写给后来人）

### 1. 长路径导致 NSIS 装不上

`UnitySetup64.exe /S /D=...` 静默安装，退出码 2，弹窗：

> `Error writing temporary file. Make sure your temp folder is valid.`

排查过程（每条都实测，不是猜）：

| 假设 | 验证 | 结论 |
|---|---|---|
| TEMP 不可写 | 查 4 个 TEMP 变量 + 实际写入测试 | ❌ 全部通过 |
| 磁盘不够 | 需要 7.54 GB，C 盘 19.2 GB | ❌ 空间充足 |
| Temp 缺 Users 权限 | 补了 ACL | ❌ 仍然失败 |
| 安装包损坏 | Authenticode `Valid`、字节数精确、7-Zip 能读 | ❌ 完好 |
| `/NCRC` 跳过校验 | 试过 | ❌ 仍然退出码 2 |

**根因：安装器所在路径太长。** 复制到 `D:\u7.exe` 再跑 → 一次成功。

```
C:\Users\...\Documents\deepseek-harness\default-workspace\unity7\UnitySetup64-7000.0.0a20.exe   ❌ 退出码 2
D:\u7.exe                                                                                        ✅ 退出码 0
```

这台机器 `LongPathsEnabled = 0`。社区同类记录：
[Unity Discussions: managing Unity version via CLI](https://discussions.unity.com/t/managing-unity-version-via-cli/1724066/8)
（2026-07，现象是 `Error launching installer`，解法是把 AppData 指到 `C:\Windows\temp`）。

### 2. curl 的 `-C` 和 `-r` 互斥

想续传又指定范围：

```
$ curl -C - -r 0-16777215 <url>
curl: option -r: is badly used here
```

自己算绝对偏移，只用 `-r`，把 stdout 追加写进分片文件：

```python
cmd = ["curl.exe", "-s", "--proxy", px, "-r", f"{a}-{b}", url]
with open(part, "ab" if have else "wb") as fh:
    subprocess.run(cmd, stdout=fh)
```

### 3. 探测协议标错，结果全废

第一版把 SOCKS5 列表当 HTTP 代理探测，7529 个候选只命中 5 个。
改成按来源标注协议后，同样的列表命中 240+。

### 4. Hub 的代理配置是黑盒

Hub 3.x 移除了显式代理菜单，依赖系统检测；但它是 Electron 多进程，
底层下载进程经常来不及捕获系统级变更。Hub 4.x 是 MSIX + WebView2，
读 `UNITY_PROXYSERVER` 优先，还会读 `UNITY_NOPROXY` 绕过列表 ——
这个变量一旦命中会让注入的代理失效，记得清掉。

验证代理到底生效没有：Hub 退出登录 → 点 Sign In → 看登录页地址。
出现 `unity.cn` 或没有 Google 登录 = 没生效。

现成工具：[HinataYoki/Unity_HubRoute](https://github.com/HinataYoki/Unity_HubRoute)
（注入代理启动 Hub，兼容 3.x NSIS 与 4.x MSIX，含 `UNITY_NOPROXY` 清理）。

---

## 已验证的环境

| 项 | 值 |
|---|---|
| Windows | 10.0.19045 |
| Python | 3.14 |
| curl | 系统自带 8.x |
| 实测版本 | Unity `7000.0.0a20`、`6000.0.85f2`、`2022.3.62f3` |
| 实测结果 | 编辑器 3.52 GB MD5 通过；Android 模块 1.63 GB + IL2CPP 284 MB MD5 通过；SDK/NDK 1.16 GB SHA384 通过 |

Linux / macOS 未实测。依赖只用到 `curl` 和标准库，理论上可移植，
但 `UnitySetup64.exe` 只适用于 Windows —— macOS 用 `.pkg`，Linux 用 `.tar.xz`。

---

## 合法性与边界

- 本项目只使用 Unity **公开的 release API**，不破解、不修改、不分发 Unity 二进制。
- 不提供任何许可证文件。Unity 的激活仍需有效账号。
- 代理池来自**公开列表**，抓的是别人的代理。请只用于下载公开文件，
  不要拿它做高频请求 —— 那是滥用他人资源。
- 若你在**中国大陆以外**，你根本不需要这个项目：Unity CDN 对正常 IP 直连即可。

---

## 致谢与相关项目

- [NoUnityCN](https://github.com/DanKE123abc/NoUnityCN) — 最早系统记录 unity.cn 重定向
- [HinataYoki/Unity_HubRoute](https://github.com/HinataYoki/Unity_HubRoute) — Hub 代理注入
- [CJMmsz/unity6-cn-usage-solutions](https://github.com/CJMmsz/unity6-cn-usage-solutions) — 国内问题合集
- 代理源：[TheSpeedX/PROXY-List](https://github.com/TheSpeedX/PROXY-List)、
  [monosans/proxy-list](https://github.com/monosans/proxy-list)、
  [proxifly/free-proxy-list](https://github.com/proxifly/free-proxy-list)、
  [openproxylist.xyz](https://api.openproxylist.xyz)、
  [proxyspace.pro](https://proxyspace.pro)、
  [geonode](https://proxylist.geonode.com)
- 相关工具（未采用，但值得知道）：[jhao104/proxy_pool](https://github.com/jhao104/proxy_pool)、
  `async-proxy-pool` —— 设计目标不同，见上文「为什么不用现成服务」

## License

MIT
