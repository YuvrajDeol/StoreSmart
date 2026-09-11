#!/usr/bin/env python3
"""Privacy proof: prints everything Sanket sends out.
Run this, then start the demo with:  --udp 127.0.0.1:9999
Every packet is a small JSON event. There are never images."""
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("127.0.0.1", 9999))
total = 0
print("Listening on 127.0.0.1:9999 - this is ALL the data leaving the system\n")
while True:
    data, _ = s.recvfrom(65535)
    total += len(data)
    print(f"{len(data):4d} bytes | total {total/1024:6.1f} KB | {data.decode()}")
