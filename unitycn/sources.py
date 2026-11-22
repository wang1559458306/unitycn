"""
unitycn.sources —— 代理源注册表与抓取
========================================
设计要点
--------
1. **每个源显式标注协议**。这是本项目踩过最狠的坑：把 SOCKS5 列表当 HTTP 探测，
   7529 个候选只命中 5 个（真实可用数约 240）。协议错了，后面的探测全白做。

2. **每行格式显式声明**。同一个仓库不同文件的行格式并不一致：

   ``plain``   ``1.2.3.4:8080``
   ``scheme``  ``socks5://1.2.3.4:8080``
   ``colon``   ``1.2.3.4:8080:United States``   （hideip.me 系列带国家名）

3. **抓取走可达的镜像**。raw.githubusercontent.com 在部分网络下不可达，
   而 ghproxy.net / gcore.jsdelivr.net 实测可达。源按优先级依次回退。

新增源只需往 ``SOURCES`` 里加一条，不需要改任何下游代码。
"""

from __future__ import annotations

import concurrent.futures as cf
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Iterable

# ---------------------------------------------------------------- 抓取出口
# 同一份文件按顺序尝试。raw 放最后：它在受限网络里最不稳。
MIRRORS = (
    "https://ghproxy.net/{url}",
    "https://gcore.jsdelivr.net/gh/{jsd}",
    "https://testingcf.jsdelivr.net/gh/{jsd}",
    "{url}",
)


@dataclass
class Source:
    name: str
    repo_path: str          # owner/repo/branch/path 形式，便于拼 jsdelivr
    raw_url: str
    protocol: str           # http / socks4 / socks5
    line_format: str        # plain / scheme / colon
    note: str = ""


# ---------------------------------------------------------------- 源清单
SOURCES: tuple[Source, ...] = (
    # ---- API 型源：不过 raw.githubusercontent.com，受限网络里更可靠 ----
    # 实测（2026-11，2000 条样本）：命中率 1.8-3.2%，与 GitHub 列表相当，
    # 但**不依赖 GitHub 镜像**，因此在内网/校园网等封 GitHub 的环境里是唯一可用的源。
    Source("openproxylist-http", "",
           "https://api.openproxylist.xyz/http.txt",
           "http", "plain", "API 型，纯文本，更新频繁"),
    Source("openproxylist-socks5", "",
           "https://api.openproxylist.xyz/socks5.txt",
           "socks5", "plain", "同上"),
    Source("proxyspace-http", "",
           "https://proxyspace.pro/http.txt",
           "http", "plain", "API 型，内容与 openproxylist 有重叠"),
    Source("proxyspace-socks5", "",
           "https://proxyspace.pro/socks5.txt",
           "socks5", "plain", "同上"),
    # geonode 是 JSON 型，需要专门解析，见下方 harvest_geonode()
    Source("geonode-http", "",
           "https://proxylist.geonode.com/api/proxy-list?limit=500&page={page}"
           "&sort_by=lastChecked&sort_type=desc&protocols=http",
           "http", "geonode", "JSON，带 upTime/国家/匿名度，单页上限 500"),

    # ---- GitHub 静态列表：内容量大，但依赖 raw.githubusercontent.com ----
    Source("TheSpeedX-http", "TheSpeedX/PROXY-List/master/http.txt",
           "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
           "http", "plain", "老牌大列表，更新频繁"),
    Source("TheSpeedX-socks5", "TheSpeedX/PROXY-List/master/socks5.txt",
           "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
           "socks5", "plain", "同上，SOCKS5 版"),
    Source("TheSpeedX-socks4", "TheSpeedX/PROXY-List/master/socks4.txt",
           "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
           "socks4", "plain", "SOCKS4，命中率高但速度普遍差"),
    Source("monosans-http", "monosans/proxy-list/main/proxies/http.txt",
           "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
           "http", "plain", "按最近验证时间排序，质量较稳"),
    Source("monosans-socks5", "monosans/proxy-list/main/proxies/socks5.txt",
           "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
           "socks5", "plain", "同上"),
    Source("proxifly-all", "proxifly/free-proxy-list/main/proxies/all/data.txt",
           "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/all/data.txt",
           "socks5", "scheme", "单文件过万条，自带 scheme 前缀"),
    Source("hideip-socks5", "zloi-user/hideip.me/main/socks5.txt",
           "https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks5.txt",
           "socks5", "colon", "带国家名，多为数据中心 IP"),
    Source("hideip-https", "zloi-user/hideip.me/main/https.txt",
           "https://raw.githubusercontent.com/zloi-user/hideip.me/main/https.txt",
           "http", "colon", "支持 CONNECT 的 http 代理"),
    Source("hideip-http", "zloi-user/hideip.me/main/http.txt",
           "https://raw.githubusercontent.com/zloi-user/hideip.me/main/http.txt",
           "http", "colon", ""),
    Source("shifty-socks5", "ShiftyTR/Proxy-List/master/socks5.txt",
           "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt",
           "socks5", "plain", "小列表，存活率一般"),
    Source("shifty-http", "ShiftyTR/Proxy-List/master/http.txt",
           "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
           "http", "plain", ""),
)

# ---------------------------------------------------------------- 行解析
_VALID_HOST = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def parse_line(line: str, fmt: str) -> tuple[str, str | None] | None:
    """返回 (host:port, 覆盖协议或 None)。不合法返回 None。

    只接受 IPv4:port —— 域名型代理在批量探测里误报率高，不值得。
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    if fmt == "scheme":
        if "://" not in line:
            return None
        sch, _, host = line.partition("://")
        sch = sch.lower()
        if sch not in ("http", "https", "socks4", "socks5"):
            return None
        # https 代理在 curl 里走 http 协议族即可（CONNECT 隧道）
        if sch == "https":
            sch = "http"
        return (host, sch) if _host_ok(host) else None

    if fmt == "colon":
        parts = line.split(":")
        if len(parts) < 2:
            return None
        host = f"{parts[0]}:{parts[1]}"
        return (host, None) if _host_ok(host) else None

    return (line, None) if _host_ok(line) else None


def parse_geonode(payload: str, default_proto: str) -> list[tuple[str, str | None]]:
    """解析 geonode 的 JSON。

    这类 API 带回 ``upTime`` / ``anonymityLevel`` / ``country`` / ``lastChecked``，
    看着很有用，但**实测表明它们对"能否访问 Unity CDN"没有预测力**：

        http    elite 前 120  → 0.8%   随机 120 → 0.0%
        socks5  elite 前 120  → 2.5%   随机 120 → 2.5%
        http    upTime top150 → 3.3%   随机 120 → 0.0%
        http    upTime>=95 前200 → 2.0%

    （见 docs/MEASUREMENTS.md 第 9 节。）原因：它们的 upTime 测的是访问普通
    网站，而我们要穿的是 Unity 的 Akamai CDN —— 目标不同，代理资质也不同。

    所以这里**只取 ip:port，不按元数据预筛**。保留字段解析能力是为了排查问题，
    不是为了过滤。
    """
    import json as _json
    try:
        data = _json.loads(payload)
    except Exception:
        return []
    out: list[tuple[str, str | None]] = []
    for row in data.get("data") or []:
        ip, port = row.get("ip"), row.get("port")
        if not ip or not port:
            continue
        hp = f"{ip}:{port}"
        if not _host_ok(hp):
            continue
        protos = row.get("protocols") or []
        p = protos[0] if protos else default_proto
        out.append((hp, "socks5" if p == "socks5" else "http"))
    return out


def _host_ok(hp: str) -> bool:
    if hp.count(":") != 1:
        return False
    host, _, port = hp.partition(":")
    return bool(_VALID_HOST.match(host)) and port.isdigit() and 0 < int(port) < 65536


# ---------------------------------------------------------------- 下载
def fetch_url(url: str, jsd: str, cache_dir: str, timeout: int = 25,
              cache_key: str = "") -> str | None:
    """按镜像顺序尝试下载，成功返回文本，全失败返回 None。

    ``cache_key`` 必须唯一标识这个 URL —— 用源名而不是文件名。
    教训：早期用 URL 末段当缓存名，导致 ``proxyspace.pro/http.txt`` 和
    ``hideip.me/http.txt`` 都存成 ``http.txt``，后者覆盖前者，于是前一个源
    被误报成"只有 1 行"。
    """
    os.makedirs(cache_dir, exist_ok=True)
    tag = cache_key or re.sub(r"[^A-Za-z0-9_.-]", "_", jsd.split("/")[-1] or "src")
    out = os.path.join(cache_dir, f"{tag}.txt")

    for tpl in MIRRORS:
        target = tpl.format(url=url, jsd=jsd) if jsd else (
            url if tpl == "{url}" else url)
        try:
            r = subprocess.run(
                ["curl.exe", "-s", "-L", "--max-time", str(timeout),
                 "-o", out, "-w", "%{http_code}", target],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout + 8)
            if r.stdout.strip() == "200" and os.path.exists(out) \
                    and os.path.getsize(out) > 64:
                return open(out, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
    return None


def harvest(sources: Iterable[Source] = SOURCES,
            cache_dir: str = ".cache/sources",
            workers: int = 6,
            verbose: bool = True,
            geo_pages: int = 2) -> dict[tuple[str, str], str]:
    """抓取全部源，返回 {(host:port, protocol): 源名} 去重后的候选集。

    ``geo_pages`` 控制 geonode 这类分页 API 抓几页（每页上限 500）。
    """
    cands: dict[tuple[str, str], str] = {}
    sources = list(sources)

    def one(src: Source):
        # 分页型：URL 里带 {page}
        pages = range(1, geo_pages + 1) if "{page}" in src.raw_url else (None,)
        n = kept = 0
        for page in pages:
            url = src.raw_url.format(page=page) if page else src.raw_url
            jsd = src.repo_path or ""
            key = f"{src.name}_p{page}" if page else src.name
            txt = fetch_url(url, jsd, cache_dir, cache_key=key)
            if txt is None:
                continue
            n += len(txt.splitlines())
            if src.line_format == "geonode":
                rows = parse_geonode(txt, src.protocol)
                for hp, proto in rows:
                    cands.setdefault((hp, proto or src.protocol), src.name)
                kept += len(rows)
            else:
                for line in txt.splitlines():
                    got = parse_line(line, src.line_format)
                    if not got:
                        continue
                    hp, override = got
                    cands.setdefault((hp, override or src.protocol), src.name)
                    kept += 1
        return src.name, kept, n

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for name, kept, total in ex.map(one, sources):
            if verbose:
                status = f"{kept} 条有效 / {total} 行" if total else "抓取失败"
                print(f"  {name:<22} {status}", file=sys.stderr)
    return cands
