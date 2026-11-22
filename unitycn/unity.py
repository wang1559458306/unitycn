"""
unitycn.unity —— Unity 官方 API 与 CDN 行为
=============================================
这个模块是整个项目最关键的事实层。三条结论都来自实测，不是推测。

**事实一：元数据不需要翻墙。**
``services.api.unity.com`` 和 ``public-cdn.cloud.unity3d.com`` 在中国大陆
可直连。版本号、直链、字节数、MD5/校验和全都能拿到。只有文件本体所在的
``download.unity3d.com`` 被区域重定向。

**事实二：重定向的目标仓库里没有国际版。**
中国大陆 IP 请求 ``download.unity3d.com`` 会收到 302，指向
``download.unitychina.cn``。而该 CDN 的 ``download_unity/`` 前缀下**没有**
国际版编辑器 —— 返回阿里云 OSS 的 ``NoSuchKey``。团结引擎在另一条独立的
``download.tuanjie.cn/download_tuanjie/`` 路径下，两者不互通。

所以 Hub 里“验证失败 / 进度条不动”不是慢，是拿到一个指向不存在文件的 302。

**事实三：区域判定只看源 IP。**
伪造 ``X-Forwarded-For`` / ``True-Client-IP`` / ``CF-Connecting-IP`` /
``X-Real-IP``、改 UA、改 Accept-Language、加查询参数，全部无效。
强制把域名解析到海外 Akamai 节点也无效 —— 判定发生在接入侧，不在节点侧。
"""

from __future__ import annotations

import base64
import json
import urllib.request
from dataclasses import dataclass

API = ("https://services.api.unity.com/unity/editor/release/v1/releases"
       "?limit=25&offset={off}&order=RELEASE_DATE_DESC"
       "&platform={platform}&architecture={arch}{stream}")

# Hub 自身的发布清单：模块直链 + checksum，中国大陆可直连
HUB_RELEASES = {
    "win32": "https://public-cdn.cloud.unity3d.com/hub/prod/releases-win32.json",
    "darwin": "https://public-cdn.cloud.unity3d.com/hub/prod/releases-darwin.json",
    "linux": "https://public-cdn.cloud.unity3d.com/hub/prod/releases-linux.json",
}

# 被区域重定向的主机（请求它一定带代理）
BLOCKED_HOSTS = ("download.unity3d.com", "netstorage.unity3d.com",
                 "beta.unity3d.com", "public-cdn.cloud.unity3d.com")


@dataclass(slots=True)
class Release:
    version: str
    url: str
    size: int
    md5: str = ""
    installed: int = 0
    release_date: str = ""

    @property
    def filename(self) -> str:
        return self.url.split("?")[0].rsplit("/", 1)[-1]


def decode_integrity(integrity: str) -> tuple[str, str]:
    """把 ``md5-base64`` 解成 ``('md5', 'hex')``。官方只给 md5 和 sha384。"""
    if not integrity or "-" not in integrity:
        return "", ""
    alg, _, b64 = integrity.partition("-")
    if alg not in ("md5", "sha256", "sha384"):
        return "", ""
    try:
        return alg, base64.b64decode(b64).hex()
    except Exception:
        return "", ""


def find_release(version: str | None = None, *, stream: str | None = None,
                 platform: str = "WINDOWS", arch: str = "X86_64",
                 max_pages: int = 40, on_page=None) -> Release:
    """按版本号查直链；version 为 None 时返回该 stream 下最新一条。"""
    st = f"&stream={stream}" if stream else ""
    for page in range(max_pages):
        url = API.format(off=page * 25, platform=platform, arch=arch, stream=st)
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.load(r)
        results = data.get("results") or []
        if not results:
            break
        for v in results:
            if version and v["version"] != version:
                continue
            if not version and not (v["version"].startswith("7000.")
                                    or v["version"].startswith("6000.")):
                continue
            for d in v.get("downloads", []):
                if d.get("platform") == platform and d.get("architecture") == arch:
                    alg, md5 = decode_integrity(d.get("integrity", ""))
                    return Release(
                        version=v["version"],
                        url=d["url"],
                        size=(d.get("downloadSize") or {}).get("value", 0),
                        md5=md5 if alg == "md5" else "",
                        installed=(d.get("installedSize") or {}).get("value", 0),
                        release_date=v.get("releaseDate", ""),
                    )
        if on_page:
            on_page(page, len(results))
    raise LookupError(f"官方 API 中找不到版本 {version or '(最新)'}")


def list_modules(version: str, *, stream: str | None = None,
                 platform: str = "WINDOWS", arch: str = "X86_64") -> list[dict]:
    """递归展开某版本的全部模块（含 subModules 的 subModules）。

    返回扁平列表，每项含 id/name/url/size/integrity/parent。
    """
    rel = find_release(version, stream=stream, platform=platform, arch=arch)
    st = f"&stream={stream}" if stream else ""
    for page in range(40):
        url = API.format(off=page * 25, platform=platform, arch=arch, stream=st)
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.load(r)
        for v in data.get("results") or []:
            if v["version"] != rel.version:
                continue
            for d in v.get("downloads", []):
                if d.get("platform") == platform and d.get("architecture") == arch:
                    out: list[dict] = []
                    _walk(d.get("modules"), out)
                    return out
        if not (data.get("results") or []):
            break
    return []


def _walk(mods, out: list, parent: str = "") -> None:
    for m in mods or []:
        out.append({
            "id": m.get("id"),
            "name": m.get("name"),
            "url": m.get("url") or m.get("downloadUrl") or "",
            "size": (m.get("downloadSize") or {}).get("value", 0),
            "integrity": m.get("integrity", ""),
            "parent": parent,
            "category": m.get("category", ""),
        })
        _walk(m.get("subModules"), out, m.get("id"))


def hub_releases(platform: str = "win32") -> list[dict]:
    """Hub 的发布清单：能直接拿到每个编辑器版本的模块直链和 checksum。"""
    with urllib.request.urlopen(HUB_RELEASES[platform], timeout=30) as r:
        return json.load(r).get("official", [])


def needs_proxy(url: str) -> bool:
    """粗判某 URL 是否位于被区域重定向的主机。"""
    return any(h in url for h in BLOCKED_HOSTS[:-1]) or \
        url.startswith("https://public-cdn.cloud.unity3d.com/download")


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"
