"""Prove Python guard denies hostname/IP attempts and permits local sockets."""
import json
import os
from pathlib import Path
import socket
from threading import Thread
assert os.environ.get("SHOWCASE_LOCAL_ONLY")=="1"
checks=[]
for name,call in [
    ("dns_external",lambda:socket.getaddrinfo("provider.example.invalid",443)),
    ("tcp_external_ip",lambda:socket.create_connection(("192.0.2.1",443),timeout=1)),
    ("connect_ex_external_ip",lambda:socket.socket().connect_ex(("192.0.2.1",443)))]:
    try:call()
    except PermissionError:checks.append({"case":name,"blocked":True})
    else:raise AssertionError(name+" escaped policy")
with socket.socket() as server:
    server.bind(("127.0.0.1",0));server.listen(1)
    def accept():
        connection,_=server.accept()
        with connection:connection.sendall(b"local")
    thread=Thread(target=accept);thread.start()
    with socket.create_connection(server.getsockname(),timeout=2) as connection:assert connection.recv(5)==b"local"
    thread.join(timeout=2)
checks.append({"case":"loopback_connection","allowed":True})
Path("runtime/ci/network-policy.json").write_text(json.dumps({"status":"passed","checks":checks},indent=2)+"\n")
print("Local-only Python network policy: 4 checks passed")
