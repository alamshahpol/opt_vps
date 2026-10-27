#!/usr/bin/env python3
"""Operator-configured stdio relay. Needs only its scoped token and Unix socket."""
import argparse
import os
import socket
import sys
import threading
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--socket", required=True)
parser.add_argument("--token-file", required=True)
args = parser.parse_args()
peer = socket.socket(socket.AF_UNIX)
peer.connect(args.socket)
peer.sendall(Path(args.token_file).read_text().strip().encode() + b"\n")


def receive():
    try:
        while chunk := peer.recv(65536):
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
    finally:
        os._exit(0)


threading.Thread(target=receive, daemon=True).start()
try:
    while chunk := os.read(sys.stdin.fileno(), 65536):
        peer.sendall(chunk)
finally:
    peer.close()
