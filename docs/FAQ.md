# 常见问题

## 安装

**Q: `unitycn: command not found`**

用 `pip install -e .` 装（在仓库根目录）。或者不装，直接 `python -m unitycn <命令>`。

**Q: 报 `python: can't open file 'unitycn'`**

你在错误的目录。要先 `cd` 到含 `unitycn/` 文件夹的仓库根目录。

---

## 下载

**Q: 下载卡在 0%，或者速度只有几十 KB/s**

先 `unitycn doctor` 看你自己网络的可达性。如果 `Unity 下载 CDN` 显示 `拦(302)` 或
`拦(404)`，说明你的 IP 在中国大陆，必须用代理池。如果是海外 IP 却仍报错，
说明是别的问题（防火墙、公司网关），把 `doctor` 的输出贴到 issue。

**Q: 免费的代理池太慢了，有没有更快的办法**

有，而且快得多。**如果你已有可用的代理（Clash / V2Ray / 公司 HTTP 代理）**，
直接往池文件里加一行：

```
http://127.0.0.1:7890	99.0
```

（地址 + TAB + 速度值，速度值给个很大的数就能排到最前。）

然后 `unitycn fetch --pool pool.txt`。免费公开代理实测最快 0.7 MB/s，
你自己的节点通常能到 5–20 MB/s。

**Q: 为什么要 96 并发？会不会把人家代理打挂**

这是**单连接限速**导致的，不是我们想并发。实测：同一个代理，1 条连接
0.74 MB/s，96 条连接 6.46 MB/s。用 1 条连接下 3.5 GB 要一个多小时。

分片是 2 MB，每个连接只拉一个 2 MB 的 Range 就断开，不是长连接占坑。
但如果你担心，可以 `--workers 16`，速度大约打五折。

**Q: 能断点续传吗**

能。分片文件放在 `<目标文件>.parts/` 下，存在且达到期望长度就跳过。
进程被 kill、断网、重启，重跑同一条命令即可。

**Q: 校验失败怎么办**

先确认文件确实下完（大小对得上）。MD5/SHA384 不匹配说明某一片坏了，
删掉 `.parts` 目录重来：

```powershell
Remove-Item .\UnitySetup64-7000.0.0a20.exe.parts -Recurse -Force
```

---

## 代理池

**Q: `unitycn pool` 跑完只有几个代理能用**

正常。2026-11 的实测：7000 个候选里存活约 240 个，其中超过 0.5 MB/s 的
只有 1–5 个。免费公开代理的现状就是这样。

**Q: 昨天建的池今天全死了**

免费代理寿命以小时计。**现用现建**，不要存着。这也是 `.gitignore` 把
`pool.txt` 排除掉的原因。

**Q: 能加自己的代理源吗**

能。编辑 `unitycn/sources.py` 的 `SOURCES`，加一条：

```python
Source("my-source", "owner/repo/branch/path.txt",
       "https://raw.githubusercontent.com/owner/repo/branch/path.txt",
       "socks5", "plain", "备注"),
```

关键是**协议**（`http`/`socks4`/`socks5`）和**行格式**（`plain`/`scheme`/`colon`）
必须标对。标错的话整个源会被探测定性成死的 —— 这是本项目第一个大坑，
详见 `docs/MEASUREMENTS.md`。

如果是 JSON 型 API，用 `line_format="geonode"`，见 `parse_geonode()`。

**Q: 为什么不直接用 `proxy_pool` / `async-proxy-pool` 那种现成服务**

它们的设计目标是给**爬虫**用：维护一个池，用 `httpbin.org/ip` 之类判断存活，
对外给 API。问题在于**校验目标不匹配**：

- 它们认为"能访问 httpbin 就是活的"，通过率通常 10–20%
- 我们要的是"能访问 Unity 的 Akamai CDN 且首字节是 PE"，通过率只有 2%

一个按它们标准"存活 100 个"的池，对我们的真实可用数还是个位数。
**等于用没校准过的尺子量长度。**

所以本项目反过来：不维护常驻服务，**现用现测、用完即弃**。每次多花
3–9 分钟，换来不会拿到"看起来有 500 个其实全是废的"池。

真想用常驻服务也行，但拿到的池要再用 `unitycn.probe.probe_many()`
按 Unity CDN 重新判活一遍。参见 `docs/MEASUREMENTS.md` 第 9.5 节。

**Q: geonode 那种带 upTime / 国家 / 匿名度的 API，不是能预筛吗**

不能。实测过：

| 组 | 命中率 |
|---|---|
| upTime top 60 | 1.7% |
| upTime >= 95 前 200 | 2.0% |
| elite 前 120 | 0.8% |
| 随机 120（基线） | 0.0% |

socks5 那边 elite 组和随机组完全一样（都是 2.5%）。

原因：它们的 `upTime` 测的是**访问普通网站**，我们要穿的是 Unity 的 Akamai。
一个能上 Google 的代理未必能过 Unity 的区域节点。

所以本项目**只取 ip:port，不按元数据预筛**。

**Q: 加了 API 源之后池子变大多少**

候选从 7082 涨到 22206（3 倍），但**最终可用数基本不变**（158 → 151）。
免费代理的可用率就是 2% 左右，扩源只增加备选，改变不了本质。

好消息是 API 源**不依赖 GitHub raw**，在内网/校园网封 GitHub 的环境里
是唯一能用的源。

---

## 安装模块

**Q: 模块 `.exe` 双击或命令行装，报 `NSIS Error: Error writing temporary file`**

**把安装器复制到短路径再运行。** 这是本项目踩得最久的一个坑，根因是路径过长
（不是 TEMP 权限、不是磁盘空间、不是文件损坏 —— 都排除过了）。

```powershell
Copy-Item .\UnitySetup-Android-Support-for-Editor-7000.0.0a20.exe D:\a.exe
D:\a.exe /S /D=D:\Unity\Editors\7000.0.0a20
```

**Q: `/D=` 的参数为什么不能加引号**

NSIS 的规定：`/D=` 必须是**最后一个参数**，且路径**不加引号**（即使含空格）。
加了引号会被当成路径的一部分。

**Q: 装完 Hub 里看不到**

两个检查：

1. 注册表 `HKLM\SOFTWARE\Unity Technologies\Installer\Unity <版本>` 下有 `Location x64`，
   指向 `<根目录>`，且 `<根目录>\Editor\Unity.exe` 存在。
2. Hub 设置里的 editor 路径包含该目录。

都不满足就在 Hub 的 Installs 页点 **Locate**，选 `<根目录>\Editor\Unity.exe`。

**Q: Android 模块装了，但编辑器说找不到 SDK/NDK**

模块 `.exe` 只装 PlaybackEngine，SDK/NDK/OpenJDK 要单独铺。用
`unitycn/install_android_sdk.ps1`，或者手工按 README 那张表解压。

铺完在编辑器里 **Preferences → External Tools** 核对路径，逐个点开确认能识别。

---

## 其他

**Q: 支持 Unity 6 吗**

支持。任何在官方 API 里能查到的版本都行：

```bash
unitycn versions --version 6000.0.85f2
unitycn fetch --version 6000.0.85f2
```

不加 `--alpha` 时默认查正式版通道。

**Q: 支持 macOS / Linux 吗**

代码本身是跨平台的（只依赖 `curl` 和标准库），但安装包不同：
macOS 是 `.pkg`，Linux 是 `.tar.xz`。`fetch` 命令用
`--platform MAC_OS --arch ARM64` 之类的参数能下到对应包，
但**安装流程和 Android 组件的铺法没在非 Windows 上验证过**。

**Q: 这算破解吗**

不算。只调用 Unity 公开的 release API，下载的是官方发布的安装包原件，
MD5 与官方一致。不修改、不绕激活、不分发许可证。

Unity 的激活（Personal 版免费）仍然需要有效账号，这一步本项目不涉及。

**Q: 我在国外，需要这个吗**

不需要。Unity CDN 对正常 IP 直连即可，直接装 Hub 就行。
