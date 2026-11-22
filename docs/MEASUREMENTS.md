# 实测记录（2026-11-22）

本文件记录项目的**事实基线**。README 里的每个数字都来自这里。
环境：Windows 10.0.19045 / 上海电信家庭宽带 / 出口 IP `112.32.193.79`（Cloudflare `loc=CN`）。

---

## 1. 封锁行为

### 1.1 302 目标

```
$ curl -I https://download.unity3d.com/download_unity/f4e960bd2f88/Windows64EditorInstaller/UnitySetup64-7000.0.0a20.exe
HTTP/1.1 302 Moved Temporarily
Server: AkamaiGHost
Location: https://download.unitychina.cn/download_unity/f4e960bd2f88/Windows64EditorInstaller/UnitySetup64-7000.0.0a20.exe
```

四个下载主机（`download.` / `netstorage.` / `beta.` / `public-cdn.cloud.`）**全部 302**。

### 1.2 目标仓库是空的

| 探测 | 结果 |
|---|---|
| `download_unity/f4e960bd2f88/.../UnitySetup64-7000.0.0a20.exe` | 404 `NoSuchKey` |
| `download_unity/b028303d8e7d/.../UnitySetup64-6000.0.85f2.exe` | 404 `NoSuchKey` |
| `download_unity/96770f904ca7/.../UnitySetup64-2022.3.62f3.exe` | 404 `NoSuchKey` |
| `download_unity/` | 404 |
| `download_unity/open-jdk/...jdk17.0.21-9....zip` | 404 |
| `/`（根） | 403 |

`Server: AliyunOSS`，错误体为 `<Code>NoSuchKey</Code>`。

### 1.3 团结引擎不镜像国际版

`download.tuanjie.cn/download_unity/...` → **404**（503 字节）。
团结引擎自有机型路径 `download.tuanjie.cn/download_tuanjie/<hash>/Windows64EditorInstaller/TuanjieSetup64.exe` 可用，
实测 6.9 MB/s；版本号形如 `2022.3.62t18`（后缀 `t`）。

### 1.4 伪造头无效

| 头 | 结果 |
|---|---|
| `X-Forwarded-For: 8.8.8.8` | 302 |
| `True-Client-IP: 8.8.8.8` | 302 |
| `CF-Connecting-IP: 8.8.8.8` | 302 |
| `X-Real-IP: 8.8.8.8` | 302 |
| `Accept-Language: en-US,en;q=0.9` | 302 |
| `User-Agent: UnityPackageManager/1.0` | 302 |
| `?x=1` / `?download=1` / `?origin=unity` | 302 |
| `--resolve` 强制到海外 Akamai IP | 302 |

### 1.5 无效路径（省得重试）

| 尝试 | 结果 |
|---|---|
| `public-cdn.cloud.unitychina.cn` | 404（同样空仓库） |
| HTTP/80 明文 | 302 |
| IPv6 直连 | 超时（本机无 IPv6 出口） |
| 公共 CORS 反代（corsproxy / allorigins / codetabs / cors.lol） | 超时或 502 |
| Cloudflare WARP 端点 `162.159.192.1:2408` | TCP 不可达（UDP 53 正常，说明非全面封 UDP） |
| Docker Hub / `unityci/editor` | registry 超时，daocloud 镜像 401 |
| `ghproxy.net` 拉 GitHub Release 大文件 | 500 / 403（只能拉小文本） |
| jsdelivr 拉大文件 | 连接直接失败 |

---

## 2. 可达性与速度

| 主机 | 直连 | 实测 |
|---|---|---|
| `services.api.unity.com` | ✅ 200 | 734 ms |
| `public-cdn.cloud.unity3d.com/hub/prod/releases-win32.json` | ✅ 200 | 81 KB |
| `dl.google.com` (NDK) | ✅ 206 | **9.2 MB/s** |
| `dl.google.com` (CMake) | ✅ 206 | 10.0 MB/s |
| `dl.google.com` (platform-tools) | ✅ 206 | 9.4 MB/s |
| `dl.google.com` (cmdline-tools) | ✅ 206 | 9.4 MB/s |
| `aka.ms` (VS bootstrapper) | ✅ 301→200 | 0.42 MB/s |
| `download.unity3d.com` | ❌ 302→404 | — |
| `github.com` | ✅ 200 | 16.1 s（首字节极慢） |
| `raw.githubusercontent.com` | ❌ 超时 | — |

---

## 3. 并发线性度

同一代理（`socks5://183.106.215.208:1080`），同一 URL，分片 2–4 MB：

| 线程 | 吞吐 |
|---|---|
| 1 | 0.74 MB/s |
| 4 | 1.59 MB/s |
| 8 | 1.15 MB/s |
| 16 | 2.54 MB/s |
| 32 | 3.68 MB/s |
| 48 | 3.69 MB/s |
| 64 | 4.83 MB/s |
| **96** | **6.46 MB/s** |
| 128 | 4.57 MB/s |
| 200 | 6.95 MB/s |

长跑验证（96 并发，512 MB，256 片）：507.2 MB / 117.8 s = **4.31 MB/s**，2 片需补跑。

多代理混合（前 10 个代理 × 8 连接 = 80 并发）：**5.02 MB/s**。

**结论：瓶颈是单连接限速，不是总带宽。**

---

## 4. 代理池质量

2026-11-22 那一轮：

| 阶段 | 数量 |
|---|---|
| 抓取候选（11 源去重后） | 7082 |
| 探测存活 | 584（另一轮 240） |
| 测速有效 | 158 |
| >0.5 MB/s | 4 |
| >1.0 MB/s | 0 |
| 最快 | 0.69 MB/s |

分布：>0.1 的 5 个，0.01–0.1 的 62 个，<0.01 的 28 个。

**这就是为什么必须高并发：单个慢，但叠起来够用。**

---

## 5. 实际下载成绩

| 文件 | 大小 | 路线 | 速度 | 校验 |
|---|---|---|---|---|
| `UnitySetup64-7000.0.0a20.exe` | 3.52 GB | 代理池 110 并发 | 2.6 MB/s，23.8 min | MD5 ✅ |
| `UnitySetup-Android-Support-...exe` | 1.63 GB | 代理池 110 并发 | 1.7 MB/s，16.6 min | MD5 ✅ |
| `UnitySetup-Windows-IL2CPP-Support-...exe` | 284 MB | 代理池 96 并发 | 1.2 MB/s，3.8 min | MD5 ✅ |
| `jdk17.0.21-9_....zip` | 110 MB | 代理池 | 0.46 MB/s，4.1 min | 大小一致 |
| `android-ndk-r27c-windows.zip` | 745 MB | **直连** | 15.3 MB/s，0.8 min | — |
| `commandlinetools-...zip` | 145 MB | **直连** | 13.6 MB/s | SHA384 ✅ |
| 其余 6 个 Google 组件 | 267 MB | **直连** | 7.7–12.7 MB/s | — |

编辑器 MD5：`447083ff7586ea475f61fdaa84a68147`（与官方 API 一致）。
`Unity.exe` 版本资源：`FileDescription = Unity 7000.0.0a20 Installer`，
`CompanyName = Unity Technologies ApS`。

---

## 6. 安装器问题

`UnitySetup64-7000.0.0a20.exe /S /D=<path>` 在长路径下**稳定失败**，退出码 2：

> `NSIS Error: Error writing temporary file. Make sure your temp folder is valid.`

排除过程：

| 假设 | 验证方法 | 结论 |
|---|---|---|
| TEMP/TMP 不可写 | 查 User/Machine/进程三组变量 + 实际写测试 | 全部存在且可写 → 推翻 |
| 磁盘空间不足 | 需 7.54 GB，C 盘余 19.2 GB | 充足 → 推翻 |
| Temp 缺 Users 写权限 | ACL 加回 `Users`/`Authenticated Users` 后重试 | 仍失败 → 推翻 |
| 安装包损坏 | Authenticode `Valid`；字节数 = 3,780,208,376；7-Zip 识别为 NSIS 且载荷完整 | 完好 → 推翻 |
| CRC 校验失败 | 加 `/NCRC` | 仍退出码 2 → 推翻 |
| **路径过长** | 复制到 `D:\u7.exe` 重跑 | **退出码 0，成功** |

机器状态：`LongPathsEnabled = 0`，`EnableLUA = 0`。

同一问题在模块安装器上可复现（`UnitySetup-Android-Support...exe` 同样需要短路径）。

社区同类记录：[Unity Discussions #1724066](https://discussions.unity.com/t/managing-unity-version-via-cli/1724066/8)（2026-07）。

---

## 7. 官方元数据（可复查）

```
GET https://services.api.unity.com/unity/editor/release/v1/releases
    ?limit=25&offset=0&order=RELEASE_DATE_DESC
    &platform=WINDOWS&architecture=X86_64&stream=ALPHA
```

7.0 alpha 共 196 个构建。最近的：

| 版本 | 日期 |
|---|---|
| `7000.0.0a20` | 2026-11-19 |
| `7000.0.0a16` | 2026-11-05 |
| `7000.0.0a12` | 2026-10-22 |
| `7000.0.0a11` | 2026-10-20 |
| `7000.0.0a10` | 2026-10-15 |
| `7000.0.0a9` | 2026-10-13 |
| `7000.0.0a8` | 2026-10-08 |
| `7000.0.0a7` | 2026-10-06（首个公开 alpha） |

`7000.0.0a20` Windows x64：

```
URL       https://download.unity3d.com/download_unity/f4e960bd2f88/Windows64EditorInstaller/UnitySetup64-7000.0.0a20.exe
download  3,780,208,376 字节 (3.52 GB)
installed 8,092,243,935 字节 (7.54 GB)
integrity md5-RHCD/3WG6kdfYf2qhKaBRw==  →  447083ff7586ea475f61fdaa84a68147
```

参数限制：`limit <= 25`（超出返回 400，`code: 55`）。

---

## 8. 模块清单陷阱

- 官方清单中 `android-sdk-tools` 的 zip 仅 **166 字节**，内容是空的 `tools/u` 目录。
  真正的 SDK 是它的 8 个 Google 子组件。
- `build-tools_r36_windows.zip` 顶层目录名为 `android-16`，必须重命名为 `36.0.0`。
- `platform-37.0_r02.zip` 顶层为 `android-37.0`（带小版本）。
- `cmake-3.22.1-windows.zip` 顶层直接是 `bin/`，不能再套一层。
- 模块 `installedSize` 远大于 `downloadSize`：Android 模块 1.63 GB → 7.29 GB。

---

## 9. 公开代理 API 的评估

很多人以为用 `proxy_pool` / `async-proxy-pool` 这类现成服务（自动爬取 + 测速 +
存活校验 + HTTP API）能省事。实测结论：**能省事，但省的不是这里的事。**

### 9.1 端点可达性

| 端点 | 结果 |
|---|---|
| `api.openproxylist.xyz/http.txt` | ✅ 200 |
| `api.openproxylist.xyz/socks5.txt` | ✅ 200 |
| `proxyspace.pro/http.txt` | ✅ 200 |
| `proxyspace.pro/socks5.txt` | ✅ 200 |
| `proxylist.geonode.com/api/proxy-list` | ✅ 200（JSON） |
| `api.proxyscrape.com/v4/...` | ❌ 000 |
| `getproxylist.com` | ❌ 000 |
| `proxy-list.download` | ❌ 502 |
| `openproxy.space` | ❌ 521 |
| `roosterkid/openproxylist`（raw） | ❌ 000 |
| `free-proxy-list.net` | ❌ 000 |

**注意到没有：失败的几乎全是 `raw.githubusercontent.com` 系和国外小站。**
这说明境内选源的第一原则是**别依赖 GitHub raw**，而不是"哪个站代理多"。

### 9.2 geonode 的元数据有没有预测力

它返回 `upTime`、`anonymityLevel`、`country`、`lastChecked`、`latency`，
看起来非常适合做预筛。**实测证明不能用来预筛：**

| 组 | 样本 | 命中率 |
|---|---|---|
| http `upTime` top 60 | 60 | 1.7% |
| http `upTime` top 150 | 150 | 3.3% |
| http `upTime >= 95` 前 200 | 200 | 2.0% |
| http `elite` 前 120 | 120 | **0.8%** |
| http 随机 120（基线） | 120 | 0.0% |
| socks5 `upTime` top 60 | 60 | 8.3% |
| socks5 `elite` 前 120 | 120 | 2.5% |
| socks5 随机 120（基线） | 120 | 2.5% |

**elite 组 0.8% 比随机基线 0.0% 看起来好，但样本太小没有统计意义；
socks5 的 elite 组和随机组完全一样（2.5%）。**

原因是它们的 `upTime` 测的是**访问普通网站**，而我们要穿的是 Unity 的
Akamai CDN —— 目标不同，代理的资质也不同。一个能访问 Google 的代理，
未必能过 Unity 的区域节点。

**结论：只取 `ip:port`，不按元数据预筛。** 这一条已写进 `sources.py` 的注释。

### 9.3 大样本命中率（每个源 400 条）

| 源 | 协议 | 命中率 |
|---|---|---|
| proxyspace | http | 3.2% |
| openproxylist | socks5 | 2.5% |
| geonode | http | 2.5% |
| openproxylist | http | 2.0% |
| geonode | socks5 | 1.8% |
| proxyspace | socks5 | 1.8% |
| **合计** | | **45/2000 = 2.2%** |

小样本（150 条）跑出过 4–6.7% 的读数，**大样本稳定在 2.2%**。
这说明：**评估代理源必须用大样本，小样本方差足以让你得出相反结论。**

### 9.4 协议偏好

早期实验（n=150）显示 socks5 命中率是 http 的 3–5 倍；
大样本（n=400/源）显示两者接近（http 2.0–3.2%，socks5 1.8–2.5%）。
**结论：没有稳定的协议偏好，两类都要抓。**

### 9.5 为什么不用现成的 proxy_pool 服务

`jhao104/proxy_pool`、`async-proxy-pool` 这类项目的设计目标是**给爬虫用**：
维护一个几百个代理的池，用 `httpbin.org/ip` 之类做存活校验，然后对外给 API。

它们的问题在于**校验目标不匹配**：

- 它们认为"能访问 httpbin 就是活的"
- 我们需要的是"能访问 Unity 的 Akamai CDN 且首字节是 PE"
- 前者通过率通常 10–20%，后者只有 2%

**一个 500 个代理的池，按它们的标准可能 100 个"存活"，但对我们的真实可用数
还是个位数。** 用它们的池，等于用一个没校准过的尺子量长度。

所以本项目的做法反过来：**不维护常驻服务，而是"现用现测"** ——
每次下载前用真实的 Unity CDN 探一遍，用完即弃。代价是每次要多花 3–9 分钟，
收益是不会拿到一个"看起来有 500 个其实全是废的"池。

### 9.6 如果你确实想要常驻服务

两种做法：

**A. 自己起一个**（推荐，可控）

本项目跑完 `unitycn pool` 后得到一个 `pool.txt`，你可以用任何 HTTP 框架
包一层 `/get` 接口。注意**定期重跑 `unitycn pool`**，因为免费代理寿命以小时计。

**B. 用现成的，但重新校准**

拿 `proxy_pool` 的池之后，**别直接信它的存活标记**，用
`unitycn.probe.probe_many()` 再过一遍：

```python
from unitycn.pool import Pool
from unitycn.probe import probe_many, bench_many

# 假设你从 proxy_pool 的 API 拿到了地址列表
cands = [("1.2.3.4:8080", "http"), ...]
alive = probe_many(cands, workers=200)      # 用 Unity CDN 重新判活
ranked = bench_many(alive)                   # 重新测速
Pool.from_ranked(ranked).save("pool.txt")
```

### 9.7 实测规模

新源加入后（2026-11-22）：

| 阶段 | 数量 |
|---|---|
| 16 个源的去重候选 | **22206** |
| 探测存活 | 466 |
| 测速有效 | 151 |
| 最快 | 0.50 MB/s |
| 中位 | 0.008 MB/s |
| 总耗时 | 8.8 分钟 |

对比加入 API 源之前：7082 候选 → 584 存活 → 158 有效。
**候选数翻了 3 倍，最终可用数基本不变** —— 免费代理的可用率就是这么低，
扩源解决不了本质问题，只是让你有更多备选。

---

## 10. 实现层面的坑

### 10.1 缓存文件名冲突

早期用 URL 末段做缓存名，导致：

```
proxyspace.pro/http.txt     → .cache/http.txt
raw.githubusercontent.com/.../hideip.me/http.txt → .cache/http.txt   ← 覆盖
```

结果 `proxyspace-http` 被误报成"只有 1 行"。改用源名做 cache_key。

### 10.2 curl 输出按 GBK 解码会崩

Windows 中文环境下 `subprocess.run(text=True)` 默认按 GBK 解码，
拉到一个含 `0xA8` 字节的响应就抛 `UnicodeDecodeError`。
必须显式 `encoding="utf-8", errors="replace"`。

---

## 复现方法

```bash
unitycn doctor                        # 复现第 2 节的可达性表
unitycn versions --alpha              # 复现第 7 节
unitycn pool --out pool.txt           # 复现第 4 节
unitycn fetch --version 7000.0.0a20 --pool pool.txt   # 复现第 5 节
```
