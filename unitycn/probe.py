"""
unitycn.probe —— 代理存活探测与测速
=====================================
这里有两个必须遵守的探测纪律，都是踩坑换来的：

**纪律一：探测必须打 offset 0 的段。**
Unity 的 Akamai CDN 对文件中间偏移经常返回超时或空响应（实测 offset
100000000 直接 curl 000），只有文件头段和尾段稳定返回 206。用中间偏移探测，
会把大量本来可用的代理误判成死代理 —— 我们复现过：7529 个候选只命中 5 个。

**纪律二：必须校验响应首字节。**
只看 HTTP 状态码会被透明代理、验证码页、运营商劫持页骗过 —— 它们同样回
200。Windows 安装包是 PE，前两字节 ``4D 5A``（"MZ"）；Android SDK 的 zip
是 ``50 4B``（"PK"）。对不上就是假的，直接丢弃。

探测量级：单次探测约 1-3KB，6000 个候选 × 2 类协议 ≈ 20MB 流量，
对提供方和本机都无压力。
"""

from __future__ import annotations

import concurrent.futures as cf
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass

# 探测目标：Unity 7 alpha 的编辑器安装包（长期有效的公开文件）
PROBE_URL = ("https://download.unity3d.com/download_unity/f4e960bd2f88/"
             "Windows64EditorInstaller/UnitySetup64-7000.0.0a20.exe")

# 合法首字节：PE(MZ) / ZIP(PK) / GZIP
VALID_SIGS = {"4D5A", "504B", "1F8B"}

_tls = threading.local()


def _scratch() -> str:
    """每线程一个临时文件，避免并发写同一路径导致互相覆盖出假阳性。"""
    if not hasattr(_tls, "path"):
        fd, p = tempfile.mkstemp(prefix="unitycn_", suffix=".bin")
        os.close(fd)
        _tls.path = p
    return _tls.path


@dataclass(slots=True)
class ProbeResult:
    proxy: str
    scheme: str
    code: str
    sig: str

    @property
    def alive(self) -> bool:
        return self.code in ("200", "206") and self.sig in VALID_SIGS


@dataclass(slots=True)
class BenchResult:
    proxy: str
    scheme: str
    bytes: int
    seconds: float

    @property
    def mbps(self) -> float:
        return self.bytes / max(self.seconds, 0.01) / 1024 / 1024


def probe(item: tuple[str, str], url: str = PROBE_URL, timeout: int = 12) -> ProbeResult:
    """探测单个代理能否取到真实文件字节。"""
    host, scheme = item
    out = _scratch()
    with open(out, "wb"):
        pass                     # 先清空：curl 失败时不写文件，残留会造成假命中
    cmd = ["curl.exe", "-s", "-o", out, "-w", "%{http_code}",
           "--proxy", f"{scheme}://{host}",
           "--connect-timeout", "6", "--max-time", str(timeout),
           "-r", "0-1023", url]   # 纪律一：固定 offset 0
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        code = r.stdout.strip()[:3]
        sig = ""
        if os.path.exists(out) and os.path.getsize(out) >= 2:
            with open(out, "rb") as f:
                sig = f.read(2).hex().upper()
        return ProbeResult(host, scheme, code, sig)
    except Exception:
        return ProbeResult(host, scheme, "ERR", "")


def bench(item: tuple[str, str, int], url: str = PROBE_URL,
          chunk_mb: int = 4, timeout: int = 22) -> BenchResult:
    """拉一个 chunk_mb 的段测吞吐。idx 用来错开不同代理的请求区间。"""
    host, scheme, idx = item
    a = idx * chunk_mb * 1024 * 1024
    b = a + chunk_mb * 1024 * 1024 - 1
    t0 = time.time()
    cmd = ["curl.exe", "-s", "-o", "NUL", "-w", "%{http_code} %{size_download}",
           "--proxy", f"{scheme}://{host}",
           "--connect-timeout", "8", "--max-time", str(timeout),
           "-r", f"{a}-{b}", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        parts = (r.stdout.split() + ["0", "0"])[:2]
        code, size = parts[0], int(parts[1])
        return BenchResult(host, scheme, size if code in ("200", "206") else 0,
                           time.time() - t0)
    except Exception:
        return BenchResult(host, scheme, 0, time.time() - t0)


def probe_many(cands, workers: int = 200, url: str = PROBE_URL,
               on_progress=None) -> list[tuple[str, str]]:
    """批量探测，返回存活代理列表。"""
    alive: list[tuple[str, str]] = []
    total = len(cands)
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for i, res in enumerate(ex.map(lambda c: probe(c, url), cands), 1):
            if res.alive:
                alive.append((res.proxy, res.scheme))
            if on_progress and (i % 500 == 0 or i == total):
                on_progress(i, total, len(alive))
    return alive


def bench_many(alive, workers: int = 150, url: str = PROBE_URL,
               chunk_mb: int = 4, on_progress=None) -> list[tuple[str, str, float]]:
    """对存活代理测速，按速度降序返回 (host, scheme, MB/s)。"""
    items = [(h, s, i % 64) for i, (h, s) in enumerate(alive)]
    ranked: list[tuple[str, str, float]] = []
    with cf.ThreadPoolExecutor(max_workers=min(workers, 150)) as ex:
        for i, res in enumerate(ex.map(lambda x: bench(x, url, chunk_mb), items), 1):
            if res.bytes > 0:
                ranked.append((res.proxy, res.scheme, res.mbps))
            if on_progress and (i % 50 == 0 or i == len(items)):
                on_progress(i, len(items), len(ranked))
    ranked.sort(key=lambda x: -x[2])
    return ranked
