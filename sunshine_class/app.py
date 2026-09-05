#!/usr/bin/env python3
"""阳光分班大屏 —— 复刻中学"阳光分班"现场大屏。

用法：
    python3 app.py                          # 默认 15 个班、855 名学生，随机名单
    python3 app.py --classes 12 --students 600
    python3 app.py --roster students.csv    # 使用真实名单（列：姓名,性别[,分数]）
    python3 app.py --title "XX市第一中学七年级阳光分班" --port 8080
    python3 app.py --host ::                # 监听所有网卡（IPv6+IPv4 双栈），供远程访问

打开浏览器访问 http://127.0.0.1:8000 ，按空格开始分班，R 重新分班，E 导出名单。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import socket
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent

SURNAMES = (
    "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘"
    "于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江"
)
GIVEN_M = "伟强磊军洋勇涛超杰鹏宇浩然轩子豪辰昊睿泽boy航亮明成建国志远博文思源乐佳一诺天佑俊熙梓晨"
GIVEN_F = "芳娜静敏丽艳娟秀霞玲桂英梅雪莹婷欣怡诗涵梓萱语嫣可馨紫菱一鸣若曦佳琪雨薇思彤晓月"


def _clean(chars: str) -> str:
    return "".join(c for c in chars if "一" <= c <= "鿿")


GIVEN_M, GIVEN_F = _clean(GIVEN_M), _clean(GIVEN_F)


def make_name(rng: random.Random, gender: str) -> str:
    pool = GIVEN_M if gender == "男" else GIVEN_F
    n = 1 if rng.random() < 0.35 else 2
    return rng.choice(SURNAMES) + "".join(rng.choice(pool) for _ in range(n))


def generate_roster(total: int, seed: int | None = None) -> list[dict]:
    """随机造一份名单（姓名 / 性别 / 摸底成绩）。"""
    rng = random.Random(seed)
    students = []
    for i in range(total):
        gender = "男" if rng.random() < 0.52 else "女"
        score = max(0, min(100, round(rng.gauss(72, 13), 1)))
        students.append(
            {
                "id": i + 1,
                "no": f"2026{i + 1:04d}",
                "name": make_name(rng, gender),
                "gender": gender,
                "score": score,
            }
        )
    return students


def load_roster(path: Path) -> list[dict]:
    """读取真实名单 CSV，列名可为 姓名/name、性别/gender、分数/score。"""
    students: list[dict] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            get = lambda *keys: next(  # noqa: E731
                (row[k].strip() for k in keys if row.get(k) and row[k].strip()), ""
            )
            gender = get("性别", "gender") or "男"
            students.append(
                {
                    "id": i + 1,
                    "no": get("学号", "考号", "no") or f"{i + 1:04d}",
                    "name": get("姓名", "name") or f"学生{i + 1}",
                    "gender": "女" if gender.startswith(("女", "F", "f")) else "男",
                    "score": float(get("分数", "成绩", "score") or 0),
                }
            )
    if not students:
        raise SystemExit(f"名单为空：{path}")
    return students


def class_sizes(total: int, classes: int) -> list[int]:
    """人数尽量均分，余数摊到前面的班（57/57/57/54… 这种）。"""
    base, extra = divmod(total, classes)
    return [base + (1 if i < extra else 0) for i in range(classes)]


def allocate(students: list[dict], classes: int, seed: int | None = None) -> list[list[dict]]:
    """阳光分班：男女分别按成绩蛇形均分，保证各班人数、男女比、平均分都均衡。"""
    rng = random.Random(seed)
    sizes = class_sizes(len(students), classes)
    buckets: list[list[dict]] = [[] for _ in range(classes)]

    for gender in ("男", "女"):
        group = [s for s in students if s["gender"] == gender]
        rng.shuffle(group)  # 同分随机，保证不可预测
        group.sort(key=lambda s: s["score"], reverse=True)
        order = list(range(classes))
        rng.shuffle(order)
        idx = 0
        while idx < len(group):
            lap = order if (idx // classes) % 2 == 0 else order[::-1]
            for c in lap:
                if idx >= len(group):
                    break
                if len(buckets[c]) < sizes[c]:
                    buckets[c].append(group[idx])
                    idx += 1

    # 极端情况下的人数兜底（某班先被填满时的溢出回填）
    for c, size in enumerate(sizes):
        while len(buckets[c]) > size:
            spare = next(i for i, b in enumerate(buckets) if len(b) < sizes[i])
            buckets[spare].append(buckets[c].pop())

    for bucket in buckets:
        rng.shuffle(bucket)  # 班内座位顺序也随机
    return buckets


def build_payload(cfg: argparse.Namespace, seed: int | None) -> dict:
    students = load_roster(Path(cfg.roster)) if cfg.roster else generate_roster(cfg.students, seed)
    buckets = allocate(students, cfg.classes, seed)
    return {
        "title": cfg.title,
        "school": cfg.school,
        "seed": seed,
        "total": len(students),
        "classes": [
            {
                "name": f"{i + 1}班",
                "count": len(b),
                "male": sum(1 for s in b if s["gender"] == "男"),
                "female": sum(1 for s in b if s["gender"] == "女"),
                "avg": round(sum(s["score"] for s in b) / len(b), 2) if b else 0,
                "students": b,
            }
            for i, b in enumerate(buckets)
        ],
    }


def payload_to_csv(payload: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["班级", "序号", "学号", "姓名", "性别", "分数"])
    for cls in payload["classes"]:
        for i, s in enumerate(cls["students"], 1):
            w.writerow([cls["name"], i, s["no"], s["name"], s["gender"], s["score"]])
    return out.getvalue()


class Server(ThreadingHTTPServer):
    """支持 IPv6 的 HTTP 服务；监听 :: 时同时接受 IPv4（双栈）。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host: str, port: int, handler):
        self.address_family = socket.AF_INET6 if ":" in host else socket.AF_INET
        self.dual_stack = host in ("::", "::0")
        super().__init__((host, port), handler)

    def server_bind(self):
        if self.address_family == socket.AF_INET6 and self.dual_stack:
            try:  # 关掉 V6ONLY，IPv4 客户端也能连
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            except OSError:
                pass
        super().server_bind()


def global_ipv6_addresses() -> list[str]:
    """列出本机的公网 IPv6 地址（Linux 用 ip 命令，其他平台走 getaddrinfo）。"""
    addrs: list[str] = []
    try:
        out = subprocess.run(
            ["ip", "-6", "-o", "addr", "show", "scope", "global"],
            capture_output=True, text=True, timeout=3,
        ).stdout
        for line in out.splitlines():
            parts = line.split()
            if "inet6" in parts:
                addrs.append(parts[parts.index("inet6") + 1].split("/")[0])
    except (OSError, subprocess.SubprocessError):
        pass
    if not addrs:
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET6):
                ip = info[4][0].split("%")[0]
                if not ip.startswith(("fe80", "::1")):
                    addrs.append(ip)
        except OSError:
            pass
    seen: set[str] = set()
    return [a for a in addrs if not (a in seen or seen.add(a))]


class Handler(BaseHTTPRequestHandler):
    cfg: argparse.Namespace
    state: dict
    lock = threading.Lock()

    def log_message(self, fmt, *args):  # 安静一点
        pass

    def _send(self, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send((HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/data":
            with self.lock:
                payload = self.state["payload"]
            self._send(
                json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8"
            )
        elif path == "/api/reshuffle":
            with self.lock:
                self.state["payload"] = build_payload(self.cfg, random.randrange(1, 10**9))
                payload = self.state["payload"]
            self._send(
                json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8"
            )
        elif path == "/api/export":
            with self.lock:
                body = payload_to_csv(self.state["payload"])
            self._send(
                ("﻿" + body).encode("utf-8"),
                "text/csv; charset=utf-8",
                {"Content-Disposition": 'attachment; filename="fenban.csv"'},
            )
        else:
            self.send_error(404)


def main() -> None:
    p = argparse.ArgumentParser(description="阳光分班大屏")
    p.add_argument("--classes", type=int, default=15, help="班级数（默认 15）")
    p.add_argument("--students", type=int, default=855, help="学生数（默认 855）")
    p.add_argument("--roster", help="真实名单 CSV：姓名,性别[,分数]")
    p.add_argument("--title", default="吴忠市第四中学七年级阳光分班", help="大屏标题")
    p.add_argument("--school", default="", help="副标题/学校名，可留空")
    p.add_argument("--seed", type=int, help="随机种子（便于复现）")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="监听地址：127.0.0.1 仅本机；:: 监听所有网卡（IPv6 + IPv4 双栈），供远程访问",
    )
    p.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    p.add_argument("--export", metavar="CSV", help="只导出分班结果到 CSV，不启动服务")
    cfg = p.parse_args()

    payload = build_payload(cfg, cfg.seed)

    if cfg.export:
        Path(cfg.export).write_text("﻿" + payload_to_csv(payload), encoding="utf-8")
        print(f"已导出：{cfg.export}")
        return

    Handler.cfg = cfg
    Handler.state = {"payload": payload}
    try:
        srv = Server(cfg.host, cfg.port, Handler)
    except OSError as exc:
        if ":" in cfg.host:
            raise SystemExit(
                f"无法在 {cfg.host}:{cfg.port} 上监听（{exc}）。\n"
                "  本机可能未启用 IPv6，或端口被占用；可改用 --host 0.0.0.0 走 IPv4。"
            ) from exc
        raise SystemExit(f"无法在 {cfg.host}:{cfg.port} 上监听（{exc}）") from exc
    shown = cfg.host if ":" not in cfg.host else f"[{cfg.host}]"
    url = f"http://{'127.0.0.1' if cfg.host in ('0.0.0.0', '::') else shown}:{cfg.port}/"
    print(f"阳光分班大屏已启动，本机访问：{url}")
    if cfg.host in ("::", "::0"):
        for ip in global_ipv6_addresses():
            print(f"  远程 IPv6 访问：http://[{ip}]:{cfg.port}/")
        print("  （远程访问需放行防火墙对应端口；家宽/云主机还要确认已分配公网 IPv6）")
    elif cfg.host == "0.0.0.0":  # noqa: S104
        print("  已监听所有 IPv4 网卡；远程访问需放行防火墙对应端口")
    print("  空格 开始/重放   R 重新随机分班   E 导出名单   F 全屏")
    if not cfg.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
