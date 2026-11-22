"""
unitycn.downloader —— 分片并发 + 代理池调度下载器
====================================================
为什么必须高并发
----------------
瓶颈不是总带宽，是**单连接限速**。实测同一个 Unity CDN 文件：

===========  =============
并发线程      吞吐
===========  =============
1            0.74 MB/s
4            1.59 MB/s
16           2.54 MB/s
32           3.68 MB/s
96           **6.46 MB/s**
128          4.57 MB/s（回落）
===========  =============

所以在代理质量一般的情况下，把文件切成小分片、开几十上百条连接，
反而能显著跑赢单线程大文件下载。分片越小调度越均匀，但元数据开销越大，
2MB 是实测下来的平衡点。

三条工程纪律
------------
1. **curl 的 ``-C`` 与 ``-r`` 互斥**。同时给会报
   ``option -r: is badly used here``。续传要自己算绝对偏移，只用 ``-r``，
   并把 stdout 追加写进分片文件。

2. **直连优先、自动降级**。Google 的 SDK/NDK 在国内直连能跑 9-15 MB/s，
   比任何代理都快；只有 Unity 自己被重定向的主机才需要代理。所以每个 URL
   先直连探一次首字节，能过就走直连多线程，过不去才挂代理。

3. **续传靠文件大小判定，不靠状态记录**。分片文件存在且达到期望长度就跳过，
   断点续传天然成立，进程被 kill 也不丢进度。
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .pool import Pool
from .probe import VALID_SIGS, probe
from .unity import human

DEFAULT_CHUNK_MB = 2
DEFAULT_WORKERS = 96


@dataclass
class Job:
    url: str
    dest: str
    size: int = 0
    integrity: str = ""          # md5-<b64> / sha384-<b64>
    workers: int = DEFAULT_WORKERS
    chunk_mb: int = DEFAULT_CHUNK_MB
    use_proxy: bool | None = None   # None = 自动判断


@dataclass
class Result:
    ok: bool
    path: str = ""
    bytes: int = 0
    seconds: float = 0.0
    route: str = ""
    verified: bool | None = None
    failed_chunks: list[int] = field(default_factory=list)

    @property
    def mbps(self) -> float:
        return self.bytes / max(self.seconds, 0.01) / 1024 / 1024


def _parts_dir(dest: str) -> str:
    return dest + ".parts"


def _fetch_one(idx: int, start: int, end: int, url: str, pool: Pool | None,
               proxy_mode: bool, workdir: str, retries: int = 10) -> tuple[int, bool]:
    """下载一个分片。返回 (序号, 是否完成)。"""
    path = os.path.join(workdir, f"c{idx:05d}")
    want = end - start + 1

    for attempt in range(retries):
        have = os.path.getsize(path) if os.path.exists(path) else 0
        if have >= want:
            return idx, True

        a = start + have if 0 < have < want else start
        b = end
        if have >= want:
            have = 0

        px = pool.pick() if (proxy_mode and pool) else None
        cmd = ["curl.exe", "-s", "--connect-timeout", "8",
               "--max-time", "70",
               "--speed-limit", "4096", "--speed-time", "12",
               "-r", f"{a}-{b}", url]
        if px:
            cmd[1:1] = ["--proxy", px]
        try:
            with open(path, "ab" if have else "wb") as fh:
                subprocess.run(cmd, stdout=fh, stderr=subprocess.DEVNULL, timeout=85)
        except (subprocess.TimeoutExpired, OSError):
            pass

        got = os.path.getsize(path) if os.path.exists(path) else 0
        if px and got <= have:
            pool.bad(px)
        elif px:
            pool.good(px)
        if got >= want:
            return idx, True
        time.sleep(min(0.4 * (attempt + 1), 2.5))
    return idx, False


def decide_route(url: str, pool: Pool | None,
                 forced: bool | None = None) -> tuple[bool, str]:
    """决定走直连还是代理。返回 (用代理?, 说明)。

    直连优先：Google / Microsoft 的地址在国内能直连且远快于代理，
    只有被 Unity 区域重定向的主机才需要代理。
    """
    if forced is not None:
        return forced, "手动指定"

    code, sig = _probe_direct(url)
    if code in ("200", "206") and sig in VALID_SIGS:
        return False, f"直连可用 (sig={sig})"
    if pool and len(pool):
        return True, f"直连被拦 (code={code or 'ERR'}) → 代理池"
    return False, f"直连被拦且无代理池，将直连重试 (code={code or 'ERR'})"


def _probe_direct(url: str, timeout: int = 12) -> tuple[str, str]:
    """不带代理试取首字节。

    跟随重定向（``-L``）：Hub 发布清单会先回 307、微软 fwlink 会先回 301，
    不跟随会把它们误判成“被拦”。真正被区域重定向的 Unity CDN 跟随后会落到
    ``download.unitychina.cn`` 并返回 404 —— 那才是要识别的信号。
    """
    import tempfile
    out = os.path.join(tempfile.gettempdir(), f"ud_probe_{os.getpid()}.bin")
    with open(out, "wb"):
        pass
    try:
        r = subprocess.run(
            ["curl.exe", "-s", "-L", "--max-redirs", "5",
             "-o", out, "-w", "%{http_code}",
             "--connect-timeout", "6", "--max-time", str(timeout),
             "-r", "0-63", url],
            capture_output=True, text=True, timeout=timeout + 5)
        code = r.stdout.strip()[:3]
        sig = ""
        if os.path.exists(out) and os.path.getsize(out) >= 2:
            with open(out, "rb") as f:
                sig = f.read(2).hex().upper()
        return code, sig
    except Exception:
        return "ERR", ""
    finally:
        try:
            os.remove(out)
        except OSError:
            pass


def download(job: Job, pool: Pool | None = None,
             on_progress: Callable[[int, int, float], None] | None = None) -> Result:
    """下载一个文件：分片并发 → 拼接 → 校验。"""
    dest = job.dest
    if job.size and os.path.exists(dest) and os.path.getsize(dest) == job.size:
        return Result(True, dest, job.size, 0.0, "已存在", None)

    proxy_mode, why = decide_route(job.url, pool, job.use_proxy)
    t0 = time.time()

    chunk = job.chunk_mb * 1024 * 1024
    size = job.size or _head_size(job.url, pool, proxy_mode)
    if not size:
        return Result(False, dest, 0, time.time() - t0, why)

    workdir = _parts_dir(dest)
    os.makedirs(workdir, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
    nchunks = (size + chunk - 1) // chunk
    chunks = [(i, i * chunk, min((i + 1) * chunk - 1, size - 1),
               job.url, pool, proxy_mode, workdir, 10) for i in range(nchunks)]

    done = [0]
    lock = threading.Lock()
    failed: list[int] = []

    def run(args):
        idx, ok = _fetch_one(*args)
        with lock:
            if ok:
                done[0] += args[2] - args[1] + 1
            else:
                failed.append(idx)
            if on_progress:
                on_progress(done[0], size, time.time() - t0)
        return ok

    for rnd in range(3):
        todo = chunks if rnd == 0 else [c for c in chunks if c[0] in failed]
        if not todo:
            break
        if rnd:
            failed.clear()
        with cf.ThreadPoolExecutor(max_workers=job.workers) as ex:
            list(ex.map(run, todo))
        if not failed:
            break

    if failed:
        return Result(False, dest, done[0], time.time() - t0, why,
                      failed_chunks=sorted(failed)[:20])

    # 拼接
    with open(dest, "wb") as w:
        for i in range(nchunks):
            with open(os.path.join(workdir, f"c{i:05d}"), "rb") as r:
                shutil.copyfileobj(r, w, 8 * 1024 * 1024)
    shutil.rmtree(workdir, ignore_errors=True)

    got = os.path.getsize(dest)
    verified = None
    if job.integrity:
        verified = _verify(dest, job.integrity)
        if verified is False:
            return Result(False, dest, got, time.time() - t0, why, verified=False)
    return Result(True, dest, got, time.time() - t0, why, verified=verified)


def _head_size(url: str, pool: Pool | None, proxy_mode: bool) -> int:
    """size 未提供时用 HEAD/Range 探测。"""
    px = pool.pick() if proxy_mode and pool else None
    cmd = ["curl.exe", "-sI", "--max-time", "20", url]
    if px:
        cmd[1:1] = ["--proxy", px]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=25).stdout
        for line in out.splitlines():
            if line.lower().startswith("content-length:"):
                return int(line.split(":", 1)[1].strip())
    except Exception:
        pass
    return 0


def _verify(path: str, integrity: str) -> bool:
    from .unity import decode_integrity
    alg, want = decode_integrity(integrity)
    if not alg:
        return True
    h = hashlib.new(alg)
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest().lower() == want.lower()


def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()
