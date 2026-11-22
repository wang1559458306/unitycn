"""
unitycn —— 在中国大陆获取 Unity 6 / 7 及组件的工具集

公开 API::

    from unitycn import find_release, Pool, build_pool, download

    build_pool("pool.txt")                 # 抓取+探测+测速
    pool = Pool.load("pool.txt")
    rel = find_release("7000.0.0a20")
    download(Job(rel.url, "UnitySetup64.exe", rel.size, "md5-..."), pool)
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = [
    "build_pool", "Pool", "Proxy", "Job", "Result", "download",
    "find_release", "list_modules", "hub_releases", "human",
    "SOURCES", "PROBE_URL",
]

from .downloader import Job, Result, download
from .pool import Pool, Proxy
from .probe import PROBE_URL, bench_many, probe_many
from .sources import SOURCES, harvest
from .unity import find_release, hub_releases, human, list_modules


def build_pool(out: str, *, workers: int = 200, quiet: bool = False) -> Pool:
    """一站式：抓源 → 探测存活 → 测速 → 写文件 → 返回 Pool。

    实测参考（2026-11，家庭宽带）：约 6000 个候选，存活 200~250 个，
    其中 >0.5 MB/s 的通常 1~5 个。**能用但不算快**，够拉 3-8 GB 的安装包。
    """
    import sys

    def log(*a):
        if not quiet:
            print(*a, file=sys.stderr, flush=True)

    log("[1/3] 抓取代理源 …")
    cands = harvest(verbose=not quiet)
    log(f"      去重后 {len(cands)} 个候选")

    log("[2/3] 探测存活（每项约 1KB）…")
    alive = probe_many(
        list(cands),
        workers=workers,
        on_progress=lambda i, n, k: log(f"      {i}/{n}  存活 {k}"),
    )
    log(f"      存活 {len(alive)} 个")

    log("[3/3] 测速（每项 4MB）…")
    ranked = bench_many(
        alive,
        on_progress=lambda i, n, k: log(f"      {i}/{n}  有效 {k}"),
    )

    pool = Pool.from_ranked(ranked)
    pool.save(out)
    st = pool.stats()
    log(f"完成：{st['total']} 个写入 {out}；最快 {st['fastest']:.2f} MB/s")
    return pool
