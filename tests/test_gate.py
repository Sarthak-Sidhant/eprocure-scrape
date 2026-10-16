import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captcha"))

import crawl  # noqa: E402


class FakeHub:
    def __init__(self, **s):
        self.settings = {"threads": 4, "delay_ms": 0, "paused": False, **s}


def run_workers(gate, n, hold=0.15):
    peak, cur, lock = [0], [0], threading.Lock()

    def work():
        with gate:
            with lock:
                cur[0] += 1
                peak[0] = max(peak[0], cur[0])
            time.sleep(hold)
            with lock:
                cur[0] -= 1
    ts = [threading.Thread(target=work) for _ in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return peak[0]


def test_gate_limits_concurrency():
    assert run_workers(crawl.Gate(3), 10) == 3


def test_gate_can_be_raised_while_running():
    g = crawl.Gate(1)
    assert run_workers(g, 6) == 1
    g.set_limit(5)
    assert run_workers(g, 10) == 5


def test_gate_limit_is_clamped():
    g = crawl.Gate(2)
    g.set_limit(999)
    assert g.limit == crawl.MAX_POOL
    g.set_limit(0)
    assert g.limit == 1


def test_obey_hub_resizes_the_gate_and_waits_out_a_pause():
    g, hub = crawl.Gate(1), FakeHub(threads=8)
    crawl.obey_hub(hub, g)
    assert g.limit == 8
    hub.settings["paused"] = True
    threading.Timer(0.5, lambda: hub.settings.update(paused=False)).start()
    t0 = time.time()
    crawl.obey_hub(hub, g)
    assert time.time() - t0 >= 0.4


def test_obey_hub_spaces_requests_by_delay():
    t0 = time.time()
    crawl.obey_hub(FakeHub(delay_ms=300), crawl.Gate(2))
    assert time.time() - t0 >= 0.29
