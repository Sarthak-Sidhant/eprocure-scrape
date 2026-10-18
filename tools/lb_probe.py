#!/usr/bin/env python3
"""Is each GePNIC portal one server or several behind a load balancer? Run from many machines (the lb-probe workflow runs it on 20
GitHub runners, so 20 egress IPs) and compare which backend each machine reaches.

For every portal: resolve its name from here, then send a few cookie-less GETs to the application URL and record, for every response
in the redirect chain, the status, the JSESSIONID node suffix (Tomcat's jvmRoute, e.g. ".geps1"), the Server header, other cookie names
(F5 BIG-IP, Citrix NetScaler and similar load balancers set their own), the IP actually connected to, and the time taken. About 4
requests per portal, spread out, so a run is light.

  python tools/lb_probe.py --out probe.json [--repeat 4]
"""
import argparse
import concurrent.futures as cf
import json
import os
import random
import socket
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from portal_list import PORTALS  # noqa: E402

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"


def egress_ip():
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://checkip.amazonaws.com"):
        try:
            return requests.get(url, timeout=10).text.strip()
        except requests.RequestException:
            continue
    return ""


def resolve(host):
    try:
        return sorted({a[4][0] for a in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
    except OSError as e:
        return [f"error: {e}"]


def peer_ip(resp):
    """The IP the response came from, read off the open socket (None once the connection is closed or reused)."""
    try:
        return resp.raw._connection.sock.getpeername()[0]
    except Exception:
        return None


def hop(resp):
    cookies = {}
    for raw in resp.raw.headers.getlist("Set-Cookie"):
        name, _, value = raw.split(";")[0].partition("=")
        cookies[name.strip()] = value
    session = cookies.pop("JSESSIONID", None)
    return {
        "url": resp.url,
        "status": resp.status_code,
        "node": (session.split(".", 1)[1] if session and "." in session else ("(no suffix)" if session else None)),
        "server": resp.headers.get("Server"),
        "via": resp.headers.get("Via"),
        "other_cookies": sorted(cookies),
        "peer": peer_ip(resp),
    }


def probe(name, url, repeat):
    host = url.split("/")[2]
    out = {"portal": name, "url": url, "dns": resolve(host), "requests": []}
    for _ in range(repeat):
        t = time.time()
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30, stream=True)
            hops = [hop(h) for h in r.history] + [hop(r)]
            r.close()
            out["requests"].append({"ms": int((time.time() - t) * 1000), "hops": hops})
        except requests.RequestException as e:
            out["requests"].append({"ms": int((time.time() - t) * 1000), "error": type(e).__name__})
        time.sleep(random.uniform(1, 3))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeat", type=int, default=4)
    ap.add_argument("--threads", type=int, default=6)
    a = ap.parse_args()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    portals = PORTALS[:]
    random.shuffle(portals)
    with cf.ThreadPoolExecutor(a.threads) as ex:
        results = list(ex.map(lambda p: probe(p[0], p[1], a.repeat), portals))
    doc = {"runner": os.environ.get("RUNNER_NAME", socket.gethostname()), "job": os.environ.get("JOB_INDEX", ""),
           "egress_ip": egress_ip(), "started": started, "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "results": sorted(results, key=lambda r: r["portal"])}
    with open(a.out, "w") as f:
        json.dump(doc, f, indent=1)
    nodes = {r["portal"]: sorted({h["node"] for q in r["requests"] for h in q.get("hops", []) if h["node"]}) for r in results}
    print(f"egress {doc['egress_ip']}: " + ", ".join(f"{p}={'/'.join(n) or '-'}" for p, n in sorted(nodes.items())))


if __name__ == "__main__":
    main()
