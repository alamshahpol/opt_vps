"""Run bridge and private broker under one nonroot account; no Docker privileges."""

import signal
import subprocess
import sys
import time
from pathlib import Path

children = []
stopping = False


def stop(_signum, _frame):
    global stopping
    stopping = True


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
status = 0
try:
    children.append(subprocess.Popen(["/usr/local/bin/whatsapp-bridge", *sys.argv[1:]]))
    children.append(subprocess.Popen([sys.executable, str(Path(__file__).with_name("consumer_broker.py"))]))
    while not stopping:
        if any(child.poll() is not None for child in children):
            status = 1
            break
        time.sleep(0.2)
finally:
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
    # Broker may have failed before its socket cleanup; never overwrite an endpoint here.
sys.exit(status)
