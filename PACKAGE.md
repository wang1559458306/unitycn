# Unity 7.0 下载与安装 —— 打包说明

这个目录打包了完整方案：**在中国大陆无 VPN 下载并安装 Unity 6/7 及其构建模块**。

## 这是什么

一个可安装的 Python 包 `unitycn` + 完整文档 + 实测数据 + 历史脚本归档。

**核心价值不是"又一个下载器"，而是把封锁机制测绘清楚了：**

- Unity CDN 对中国大陆 IP 302 到一个**没有国际版文件的空仓库**，
  所以 Hub 的"验证失败"不是网慢，是永久等不到
- 区域判定只看源 IP，7 种伪造头全部无效
- **元数据 API 国内可直连** —— 版本、直链、MD5 都不需要翻墙
- **Google 的 Android SDK/NDK 国内直连 9–15 MB/s**，比翻墙快一个数量级

## 快速开始

本机装了 Python 但没有网络装依赖？用自带脚本（不依赖 pip）：

```powershell
.\install_offline.ps1
```

或者用 pip：

```bash
pip install -e .
```

Windows 上如果 pip 报 `No matching distribution found for setuptools`，
说明构建隔离拉不到包，加参数：

```bash
pip install --no-build-isolation -e .
```

装好后：

```bash
unitycn doctor                              # 看环境与连通性
unitycn versions --alpha                    # 查版本与直链
unitycn pool --out pool.txt                 # 建代理池（约 5 分钟）
unitycn fetch --version 7000.0.0a20 --pool pool.txt
unitycn modules --version 7000.0.0a20 --alpha
unitycn fetchm --version 7000.0.0a20 --alpha --only android,windows-il2cpp
```

不想装也行，直接在仓库根目录 `python -m unitycn <命令>`。

## 文件导航

| 路径 | 内容 |
|---|---|
| `README.md` | **主文档**：封锁原理、可达性矩阵、并发数据、离线装模块、踩坑记录 |
| `docs/MEASUREMENTS.md` | **实测基线**：每个数字对应的命令和输出，可自行复现 |
| `docs/FAQ.md` | 常见问题（含"为什么 96 并发""免费池太慢怎么办"） |
| `CONTRIBUTING.md` | 怎么补代理源、怎么报失效源 |
| `unitycn/` | 包源码（9 个模块 + Android SDK 铺装脚本） |
| `tests/test_units.py` | 16 个单元测试，不依赖网络 |
| `archive/` | 早期探索脚本（功能已并入包，保留作证据） |
| `modules/` | 已下载的 Android SDK/NDK 组件（1.16 GB，可直连重下） |

## 已实测完成的事

| 项目 | 结果 |
|---|---|
| Unity 7000.0.0a20 编辑器 | 3.52 GB，MD5 `447083ff...` 通过 |
| Android Build Support 模块 | 1.63 GB，MD5 通过 |
| Windows IL2CPP 模块 | 284 MB，MD5 通过 |
| Android SDK/NDK/OpenJDK | 1.16 GB，SHA384 通过 |
| 编辑器安装 | `D:\Unity\Editors\7000.0.0a20`，已登记注册表，Hub 可识别 |
| Android 组件铺装 | 10 项校验全通过（java / adb / clang / aapt2 / 3 个 platform / cmake / sdkmanager） |

## 注意事项

**代理池不要提交到仓库。** 免费代理寿命以小时计，现用现建。
`.gitignore` 已排除 `pool.txt` 和所有代理列表。

**如果你已有可用的代理，别用免费池。** 往池文件加一行就行：

```
http://127.0.0.1:7890	99.0
```

比抓公开代理快 5–20 倍。

**安装器必须放短路径。** `NSIS Error: Error writing temporary file` 的根因是
路径过长，不是权限或空间问题 —— 已逐项排除。复制到 `D:\u7.exe` 再运行。

## 边界

只调用 Unity 公开 API，下载官方原件并校验。不修改、不绕激活、不分发许可证。
Unity 的激活仍需有效账号。

代理来自公开列表，请只用于下载公开文件，不要做高频请求。

## 许可

MIT（见 `LICENSE`，含代理使用的附加说明）。
