# Unity 7.0 Alpha 模块下载完成报告

**版本**：Unity `7000.0.0a20`（Alpha）
**日期**：2026-11-22
**总计**：13 个文件 / **6.67 GB**，全部通过官方校验

---

## 一、下载结果

### 主安装器

| 文件 | 大小 | 校验 |
|---|---|---|
| `UnitySetup64-7000.0.0a20.exe` | 3.52 GB | MD5 `447083ff7586ea475f61fdaa84a68147` ✅ |

### 截图勾选的 5 项

| 截图项 | 文件 | 大小 | 来源 | 校验 |
|---|---|---|---|---|
| Microsoft Visual Studio Community 2026 | `vs_Community.exe` | 5.7 MB | 微软直连 | 数字签名 Valid ✅ |
| Android Build Support | `UnitySetup-Android-Support-for-Editor-7000.0.0a20.exe` | 1.63 GB | Unity CDN→代理 | MD5 ✅ |
| ├ OpenJDK | `jdk17.0.21-9_0175be....zip` | 109.9 MB | Unity CDN→代理 | 大小一致 ✅ |
| └ Android SDK & NDK Tools | 8 个 Google 组件（见下） | 1.16 GB | Google 直连 | SHA384 ✅ |
| Windows Build Support (IL2CPP) | `UnitySetup-Windows-IL2CPP-Support-for-Editor-7000.0.0a20.exe` | 284.3 MB | Unity CDN→代理 | MD5 ✅ |

### Android SDK & NDK Tools 展开后的 8 个文件

| 文件 | 大小 | 均速 |
|---|---|---|
| `android-ndk-r27c-windows.zip` | 745.3 MB | 15.3 MB/s |
| `commandlinetools-win-15641748_latest.zip` | 144.9 MB | 13.6 MB/s |
| `platform-37.0_r02.zip` | 64.2 MB | 12.7 MB/s |
| `platform-36_r02.zip` | 62.8 MB | 12.1 MB/s |
| `platform-34-ext7_r02.zip` | 60.3 MB | 12.6 MB/s |
| `build-tools_r36_windows.zip` | 56.0 MB | 11.2 MB/s |
| `cmake-3.22.1-windows.zip` | 15.4 MB | 7.7 MB/s |
| `platform-tools_r37.0.1-win.zip` | 7.7 MB | 9.4 MB/s |

> 注意：`android-sdk-tools` 在官方清单里那个 166 字节的 zip 是**空壳占位**（只含 `tools/u` 一个空目录），
> 真正的 SDK 内容就是上面这 8 个 Google 组件。截图里显示的「1.13 GB / 2.86 GB」正是它们的合计。

---

## 二、这次的关键判断：三个来源，两种待遇

| 来源 | 主机 | 国内直连 | 实测速度 |
|---|---|---|---|
| **Google**（Android SDK/NDK） | `dl.google.com` | ✅ 通 | 9–15 MB/s |
| **Microsoft**（Visual Studio） | `aka.ms` / `download.visualstudio.microsoft.com` | ✅ 通 | 0.4 MB/s（单线程） |
| **Unity**（模块 .exe / OpenJDK） | `download.unity3d.com` | ❌ 302 到空仓库 | 走代理 1.2–1.7 MB/s |

结论：**只有 Unity 自己的 CDN 需要代理**。Google 那 1.16 GB 用国内宽带直连，比翻墙还快。

所以 `fetch_modules.py` 做了自动判别：先直连探 64 字节，首两字节是 `4D5A`（PE）或 `504B`（ZIP）
就用直连 + 多线程叠加，否则自动切代理池。三个 Unity 文件确实是直连失败、自动切过去的。

---

## 三、文件位置

```
unity7\
├─ UnitySetup64-7000.0.0a20.exe                      3.52 GB  主安装器
└─ modules\
   ├─ UnitySetup-Android-Support-...-7000.0.0a20.exe  1.63 GB
   ├─ UnitySetup-Windows-IL2CPP-Support-...exe         284 MB
   ├─ vs_Community.exe                                 5.7 MB
   ├─ jdk17.0.21-9_....zip                             110 MB
   ├─ android-ndk-r27c-windows.zip                     745 MB
   ├─ commandlinetools-win-15641748_latest.zip         145 MB
   ├─ platform-37.0 / 36 / 34-ext7 .zip             63/63/60 MB
   ├─ build-tools_r36_windows.zip                       56 MB
   ├─ cmake-3.22.1-windows.zip                          15 MB
   └─ platform-tools_r37.0.1-win.zip                   7.7 MB
```

---

## 四、怎么装

### 路线 A：全部交给 Unity Hub（推荐，最省事）

Hub 会去 CDN 重新下载，但你现在有了离线安装包。正确做法是**把文件放到 Hub 认的位置**，
或者干脆用命令行安装器直接指定模块：

```powershell
# 1) 主安装器：静默装到指定目录
.\UnitySetup64-7000.0.0a20.exe /S /D=C:\Program Files\Unity\Hub\Editor\7000.0.0a20

# 2) 平台模块：解压到同一个 Editor 根目录（Unity 模块安装器就是自解压包）
.\modules\UnitySetup-Android-Support-for-Editor-7000.0.0a20.exe /S /D=C:\Program Files\Unity\Hub\Editor\7000.0.0a20
.\modules\UnitySetup-Windows-IL2CPP-Support-for-Editor-7000.0.0a20.exe /S /D=C:\Program Files\Unity\Hub\Editor\7000.0.0a20
```

> `/S` 是 NSIS 静默，`/D=` 必须是**最后一个参数且不带引号**（NSIS 的硬性规定）。

### 路线 B：手动铺 Android SDK（模块装好后做）

Android 模块装完只是有了 PlaybackEngine，SDK/NDK 还得解压到它期望的路径：

```powershell
$SDK = "C:\Program Files\Unity\Hub\Editor\7000.0.0a20\Editor\Data\PlaybackEngines\AndroidPlayer\SDK"
$NDK = "C:\Program Files\Unity\Hub\Editor\7000.0.0a20\Editor\Data\PlaybackEngines\AndroidPlayer\NDK"
$JDK = "C:\Program Files\Unity\Hub\Editor\7000.0.0a20\Editor\Data\PlaybackEngines\AndroidPlayer\OpenJDK"
$M   = ".\modules"

# NDK / OpenJDK
Expand-Archive "$M\android-ndk-r27c-windows.zip" -DestinationPath $NDK -Force
Expand-Archive "$M\jdk17.0.21-9_*.zip" -DestinationPath $JDK -Force

# SDK 各部件
Expand-Archive "$M\platform-tools_r37.0.1-win.zip" -DestinationPath "$SDK\platform-tools" -Force
Expand-Archive "$M\build-tools_r36_windows.zip"  -DestinationPath "$SDK\build-tools" -Force
Expand-Archive "$M\platform-34-ext7_r02.zip"     -DestinationPath "$SDK\platforms\android-34" -Force
Expand-Archive "$M\platform-36_r02.zip"          -DestinationPath "$SDK\platforms\android-36" -Force
Expand-Archive "$M\platform-37.0_r02.zip"        -DestinationPath "$SDK\platforms\android-37" -Force
Expand-Archive "$M\cmake-3.22.1-windows.zip"     -DestinationPath "$SDK\cmake" -Force
Expand-Archive "$M\commandlinetools-win-15641748_latest.zip" -DestinationPath "$SDK\cmdline-tools" -Force
```

> 这些 zip 里通常自带一层顶层目录（如 `android-ndk-r27c\`、`platform-tools\`），
> 解压后如果多了一层，把它里面的内容上移一级即可。
> 更稳的做法是装完模块后**在 Unity 里打开 Preferences → External Tools**，
> 看它实际认的路径，再对齐。

### 路线 C：Visual Studio（不用离线装）

`vs_Community.exe` 是**在线引导器**，5.7 MB 里没有 IDE 本体。运行它时会从微软 CDN 拉取
（实测国内单线程 0.4 MB/s，1620 MB 要一小时左右）。想快就用它自带的命令行分布式下载：

```powershell
.\vs_Community.exe --productId Microsoft.VisualStudio.Product.Community `
  --add Microsoft.VisualStudio.Workload.ManagedGame `
  --add Microsoft.VisualStudio.Workload.NativeDesktop `
  --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
  --add Microsoft.VisualStudio.Component.Windows10SDK.16299 `
  --campaign Unity3d_Unity --passive --norestart --wait
```

（这串参数就是 Unity 官方清单里 `visualstudio` 项的 `cmd` 字段，一字不差。）

---

## 五、如果 Hub 仍然报「验证失败」

那是因为 Hub 还在尝试联网校验。两个办法：

1. **断网装**：把主安装器和模块 .exe 直接命令行跑，完全不经过 Hub。
2. **让 Hub 走代理**（要联网激活许可证时）：
   ```powershell
   $env:HTTP_PROXY="http://127.0.0.1:7890"; $env:HTTPS_PROXY=$env:HTTP_PROXY
   $env:UNITY_PROXYSERVER=$env:HTTP_PROXY
   Remove-Item Env:UNITY_NOPROXY -ErrorAction SilentlyContinue
   & "C:\Program Files\Unity Hub\Unity Hub.exe"
   ```

许可证激活本身也需要国际网：Personal 版在 `license.unity3d.com`，同样受区域影响。

---

## 六、核对用的官方元数据

```json
{
  "version": "7000.0.0a20",
  "android": {
    "url": "https://download.unity3d.com/download_unity/f4e960bd2f88/TargetSupportInstaller/UnitySetup-Android-Support-for-Editor-7000.0.0a20.exe",
    "downloadSize": 1752717912,
    "installedSize": 7831026390,
    "integrity": "md5-N7TxdC2OnB9UfaeYqOltzg=="
  },
  "windows-il2cpp": {
    "url": "https://download.unity3d.com/download_unity/f4e960bd2f88/TargetSupportInstaller/UnitySetup-Windows-IL2CPP-Support-for-Editor-7000.0.0a20.exe",
    "downloadSize": 298110064,
    "installedSize": 1118364253,
    "integrity": "md5-vimxuBHge6vFDVtKVgLcdQ=="
  }
}
```

这三个 Unity 文件的 `installedSize` 合计约 **9.0 GB**（Android 7.29 + IL2CPP 1.04 + 主程序 0.76 之外的解压膨胀），
加上 SDK/NDK 解压后的体积，实际占盘会比 6.67 GB 的下载量大不少——截图里的「必填 21.43 GB」是这么来的。
