# 贡献指南

## 最有价值的贡献

### 1. 补充 / 修正代理源

`unitycn/sources.py` 里每个源必须标对两个字段：

| 字段 | 取值 | 说明 |
|---|---|---|
| `protocol` | `http` / `socks4` / `socks5` | 该列表里代理的协议 |
| `line_format` | `plain` / `scheme` / `colon` | 每行的格式 |

```python
# plain :  1.2.3.4:8080
# scheme:  socks5://1.2.3.4:8080
# colon :  1.2.3.4:8080:United States
```

**标错的后果**：整个源会被探测定性成死的。本项目第一版就把 SOCKS5 列表
当 HTTP 探，7529 个候选只命中 5 个（真实约 240 个）。

加源后请附一次 `unitycn pool` 的实测结果（存活数 / 最快速度），否则无法判断该源是否值得保留。

### 2. 报告失效的源

代理源会静默失效。如果某个源连续多次抓取失败或命中率为 0，开 issue 贴：

```
源名：
抓取结果：（成功/失败，多少行）
有效条数：
```

### 3. 补非 Windows 的安装流程

目前只验证了 Windows。以下都缺实测：

- macOS `.pkg` 的静默安装参数
- Linux `.tar.xz` 的解压布局
- 非 Windows 上 Android SDK/NDK 的路径约定

如果你在 macOS/Linux 上跑通了，请把具体命令和目录结构写进 README，
并注明你的发行版和版本。

### 4. 更新 `docs/MEASUREMENTS.md`

Unity 会改 CDN 行为、API 结构、模块清单。任何一项变化都应更新实测记录。
**改数字必须附复现命令**，不能只写结论。

---

## 不接受的内容

- **把 `pool.txt` / 代理列表提交进仓库**。免费代理寿命以小时计，提交了第二天全是死节点，
  还会误导来提 issue 的人。`.gitignore` 已排除。
- **下载产物**（`*.exe` / `*.zip` / `modules/`）。体积大且可再生成。
- **任何绕过 Unity 许可证激活的代码**。本项目只下载官方公开文件，
  激活仍需有效账号。
- **针对特定目标的扫描/爆破代码**。抓代理是为了下载公开文件，不是拿来做攻击流量。

---

## 开发

```bash
pip install -e .
python -m unittest discover -s tests -v
python -m unitycn doctor
```

### 代码约定

- 只用标准库 + `curl` 子进程。不引入第三方依赖 —— 这个项目的用户往往处在
  受限网络里，装包本身就可能是障碍。
- 新增的每个"为什么这样写"都要在注释里说明**踩过的坑**，而不只是描述行为。
  例：`probe.py` 里为什么必须打 offset 0。
- 平台相关分支要显式判断 `sys.platform`，不要假设 `curl` 叫 `curl`。

### 提交前自检

```bash
python -m unittest discover -s tests      # 必须全绿
python -m unitycn doctor                  # 确认没有破坏 CLI
python -m unitycn modules --version 7000.0.0a20 --alpha   # 确认 API 层没坏
```

### 测试原则

单元测试**不依赖网络**。凡是需要联网的验证，放在 `.github/workflows/ci.yml`
的 `metadata` job 里，并允许失败（`continue-on-error`）—— Unity 改接口不应
让整个 CI 红掉。

---

## 提交信息

```
type: 简述

type 取 fix / feat / docs / refactor / test / chore
```

涉及实测数据的提交，正文里贴命令和输出。
