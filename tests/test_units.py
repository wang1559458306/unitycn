"""单元测试：不依赖网络，验证解析、池调度、校验等纯逻辑。"""

import base64
import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unitycn.pool import Pool, Proxy
from unitycn.probe import ProbeResult
from unitycn.sources import parse_line
from unitycn.unity import decode_integrity


class TestParseLine(unittest.TestCase):
    """行解析：协议与格式标错会让整个池作废，这是历史 bug 的回归测试。"""

    def test_plain(self):
        self.assertEqual(parse_line("1.2.3.4:8080", "plain"), ("1.2.3.4:8080", None))

    def test_plain_rejects_junk(self):
        for bad in ("", "#comment", "1.2.3.4", "1.2.3.4:abc",
                    "example.com:8080", "1.2.3.4:8080:US"):
            self.assertIsNone(parse_line(bad, "plain"), bad)

    def test_scheme(self):
        self.assertEqual(parse_line("socks5://1.2.3.4:1080", "scheme"),
                         ("1.2.3.4:1080", "socks5"))

    def test_scheme_https_maps_to_http(self):
        # https 代理在 curl 里走 http 协议族（CONNECT 隧道）
        self.assertEqual(parse_line("https://1.2.3.4:443", "scheme"),
                         ("1.2.3.4:443", "http"))

    def test_scheme_rejects_unknown(self):
        self.assertIsNone(parse_line("ftp://1.2.3.4:21", "scheme"))

    def test_colon_with_country(self):
        self.assertEqual(parse_line("1.2.3.4:8080:United States", "colon"),
                         ("1.2.3.4:8080", None))

    def test_port_range(self):
        self.assertIsNone(parse_line("1.2.3.4:0", "plain"))
        self.assertIsNone(parse_line("1.2.3.4:99999", "plain"))


class TestProbeResult(unittest.TestCase):
    def test_alive_requires_valid_signature(self):
        # 只看状态码会被劫持页骗过，必须校验首字节
        self.assertTrue(ProbeResult("h", "http", "206", "4D5A").alive)
        self.assertTrue(ProbeResult("h", "http", "200", "504B").alive)
        self.assertFalse(ProbeResult("h", "http", "200", "3C21").alive)  # "<!"
        self.assertFalse(ProbeResult("h", "http", "404", "4D5A").alive)


class TestPool(unittest.TestCase):
    def test_roundtrip(self):
        ranked = [("1.1.1.1:1", "http", 2.0), ("2.2.2.2:2", "socks5", 0.5)]
        pool = Pool.from_ranked(ranked)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "pool.txt")
            pool.save(p)
            back = Pool.load(p)
        self.assertEqual(len(back), 2)
        self.assertAlmostEqual(back.items[0].speed, 2.0)

    def test_pick_prefers_fast_but_random(self):
        procs = [Proxy(f"10.0.0.{i}:1", speed=float(i)) for i in range(1, 21)]
        pool = Pool(procs)
        picks = {pool.pick() for _ in range(200)}
        # 应只在前 40%（8 个）里挑，不应出现最慢的
        self.assertLessEqual(len(picks), 8)
        self.assertNotIn("10.0.0.1:1", picks)

    def test_bad_eventually_removed(self):
        pool = Pool([Proxy("1.1.1.1:1", 1.0)], max_fails=4)
        for _ in range(4):
            pool.bad("1.1.1.1:1")
        self.assertEqual(pool.alive, 0)

    def test_pool_resets_when_all_dead(self):
        # 全池降权时必须重置，否则死锁、无法继续下载
        pool = Pool([Proxy("1.1.1.1:1", 1.0)], max_fails=2)
        pool.bad("1.1.1.1:1")
        pool.bad("1.1.1.1:1")
        self.assertEqual(pool.alive, 0)
        self.assertIsNotNone(pool.pick())

    def test_empty(self):
        self.assertIsNone(Pool().pick())
        self.assertFalse(Pool())


class TestIntegrity(unittest.TestCase):
    def test_md5_decode(self):
        raw = bytes.fromhex("447083ff7586ea475f61fdaa84a68147")
        b64 = base64.b64encode(raw).decode()
        self.assertEqual(decode_integrity(f"md5-{b64}"),
                         ("md5", "447083ff7586ea475f61fdaa84a68147"))

    def test_unknown_alg(self):
        self.assertEqual(decode_integrity("crc-abc"), ("", ""))
        self.assertEqual(decode_integrity(""), ("", ""))


class TestParseGeonode(unittest.TestCase):
    """JSON 型 API 的解析。"""

    def _payload(self, rows):
        import json
        return json.dumps({"data": rows, "total": len(rows)})

    def test_basic(self):
        from unitycn.sources import parse_geonode
        p = self._payload([
            {"ip": "1.2.3.4", "port": "8080", "protocols": ["http"]},
            {"ip": "5.6.7.8", "port": "1080", "protocols": ["socks5"]},
        ])
        self.assertEqual(parse_geonode(p, "http"),
                         [("1.2.3.4:8080", "http"), ("5.6.7.8:1080", "socks5")])

    def test_no_protocols_uses_default(self):
        from unitycn.sources import parse_geonode
        p = self._payload([{"ip": "1.2.3.4", "port": "8080"}])
        self.assertEqual(parse_geonode(p, "socks5"), [("1.2.3.4:8080", "socks5")])

    def test_skips_invalid(self):
        from unitycn.sources import parse_geonode
        p = self._payload([
            {"ip": "not-an-ip", "port": "80", "protocols": ["http"]},
            {"ip": "1.2.3.4"},                       # 缺 port
            {"port": "80", "protocols": ["http"]},   # 缺 ip
            {"ip": "1.2.3.4", "port": "99999", "protocols": ["http"]},
        ])
        self.assertEqual(parse_geonode(p, "http"), [])

    def test_bad_json_returns_empty(self):
        from unitycn.sources import parse_geonode
        self.assertEqual(parse_geonode("<html>502</html>", "http"), [])
        self.assertEqual(parse_geonode("", "http"), [])


class TestSourceRegistry(unittest.TestCase):
    def test_all_sources_wellformed(self):
        from unitycn.sources import SOURCES
        self.assertGreater(len(SOURCES), 10)
        names = [s.name for s in SOURCES]
        self.assertEqual(len(names), len(set(names)), "源名必须唯一（缓存键依赖它）")

    def test_api_sources_have_no_jsd(self):
        """API 型源不该走 jsdelivr 镜像。"""
        from unitycn.sources import SOURCES
        api = [s for s in SOURCES if not s.repo_path]
        self.assertTrue(api, "应有不依赖 GitHub 的 API 型源")
        for s in api:
            self.assertNotIn("raw.githubusercontent.com", s.raw_url, s.name)

    def test_line_format_known(self):
        from unitycn.sources import SOURCES
        valid = {"plain", "scheme", "colon", "geonode"}
        for s in SOURCES:
            self.assertIn(s.line_format, valid, s.name)


class TestHuman(unittest.TestCase):
    def test_human(self):
        from unitycn.unity import human
        self.assertEqual(human(0), "0.0B")
        self.assertEqual(human(1024), "1.0KB")
        self.assertEqual(human(1536), "1.5KB")


if __name__ == "__main__":
    unittest.main(verbosity=2)
