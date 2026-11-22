"""
unitycn.pool —— 代理池的持久化与调度
=====================================
池的存续方式直接影响可用性：

* 免费代理的寿命以小时计。**现用现建**，不要提交到仓库当静态资源
  （提交了第二天就全是死节点，还会误导读 issue 的人）。

* 调度要“在好的里面随机挑”。如果永远挑最快那个，它的出口很快被目标站
  限流；如果完全均匀随机，又会被大量龟速节点拖垮。实践值：取速度前 40%
  随机 —— 既分散出口，又不浪费带宽。

* 失败降权而不是立即淘汰。免费代理经常是间歇性的，连续失败 3~4 次才
  认定死亡；全池都降权时整体重置，避免死锁。
"""

from __future__ import annotations

import os
import random
import threading
from dataclasses import dataclass, field


@dataclass
class Proxy:
    proxy: str              # 建议存 "scheme://host:port"
    speed: float = 0.0      # MB/s，来自测速
    fails: int = 0

    @property
    def scheme(self) -> str:
        return self.proxy.split("://", 1)[0] if "://" in self.proxy else "http"

    @property
    def hostport(self) -> str:
        return self.proxy.split("://", 1)[1] if "://" in self.proxy else self.proxy


class Pool:
    """线程安全代理池。"""

    def __init__(self, items=None, max_fails: int = 4, elite_ratio: float = 0.4):
        self.items: list[Proxy] = list(items or [])
        self.max_fails = max_fails
        self.elite_ratio = elite_ratio
        self._lock = threading.Lock()
        self._rr = 0
        self._resort()

    def _resort(self):
        self.items.sort(key=lambda x: -x.speed)

    # ------------------------------------------------------------ 读写
    @classmethod
    def load(cls, path: str, **kw) -> "Pool":
        """读 ``scheme://host:port<TAB>speed`` 格式。"""
        items = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    addr, _, spd = line.partition("\t")
                    if not addr:
                        continue
                    items.append(Proxy(addr, float(spd or 0)))
        return cls(items, **kw)

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for p in self.items:
                f.write(f"{p.proxy}\t{p.speed:.3f}\n")

    @classmethod
    def from_ranked(cls, ranked, **kw) -> "Pool":
        """接受 [(host, scheme, mbps), ...]。"""
        return cls([Proxy(f"{s}://{h}", mb) for h, s, mb in ranked], **kw)

    # ------------------------------------------------------------ 调度
    def pick(self) -> str | None:
        with self._lock:
            live = [p for p in self.items if p.fails < self.max_fails]
            if not live:
                for p in self.items:      # 全池降权 → 重置，避免死锁
                    p.fails = 0
                live = self.items
            if not live:
                return None
            n = max(3, int(len(live) * self.elite_ratio))
            return random.choice(live[:n]).proxy

    def good(self, proxy: str) -> None:
        with self._lock:
            for p in self.items:
                if p.proxy == proxy or p.hostport == proxy:
                    p.fails = max(0, p.fails - 1)
                    break

    def bad(self, proxy: str) -> None:
        with self._lock:
            for p in self.items:
                if p.proxy == proxy or p.hostport == proxy:
                    p.fails += 1
                    break

    # ------------------------------------------------------------ 观测
    @property
    def alive(self) -> int:
        return sum(1 for p in self.items if p.fails < self.max_fails)

    def stats(self) -> dict:
        sp = [p.speed for p in self.items if p.fails < self.max_fails]
        return {
            "total": len(self.items),
            "alive": len(sp),
            "fastest": max(sp) if sp else 0.0,
            "median": sorted(sp)[len(sp) // 2] if sp else 0.0,
        }

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)
