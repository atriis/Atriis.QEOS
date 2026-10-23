"""wait-for.py <url> ... -- a loop job's init container (ADR-038): waits until each URL answers 200, in order, as Compose's
depends_on condition service_healthy makes the job wait for the service's health check. Gives up after
WAIT_FOR_SECONDS (300) with exit 1, so the kubelet restarts the init container and the pod's events say why. Runs in
the job's own image (Python's standard library only)."""
import os
import sys
import time
import urllib.request

timeout = float(os.environ.get("WAIT_FOR_SECONDS", "300"))
deadline = time.monotonic() + timeout
for url in sys.argv[1:]:
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    print(f"wait-for: {url} answers 200", flush=True)
                    break
                last = f"HTTP {response.status}"
        except Exception as exc:  # refused, timed out, HTTP error: all mean "not yet"
            last = f"{type(exc).__name__}: {exc}"
        if time.monotonic() >= deadline:
            print(f"wait-for: {url} not healthy after {timeout:.0f} s ({last})", file=sys.stderr, flush=True)
            sys.exit(1)
        time.sleep(2)
