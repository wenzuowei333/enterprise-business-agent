"""Opt-in local-only Python test policy, inherited by owned worker processes."""
import ipaddress
import json
import os
import socket

if os.environ.get("SHOWCASE_LOCAL_ONLY") == "1":
    _resolve = socket.getaddrinfo
    _connect = socket.socket.connect
    _connect_ex = socket.socket.connect_ex
    def allowed(host):
        if host in {None, "localhost", "testserver"}: return True
        try: return ipaddress.ip_address(host).is_loopback
        except (ValueError, TypeError): return False
    def deny(host):
        path=os.environ.get("NETWORK_AUDIT_FILE")
        if path:
            with open(path,"a") as output:
                output.write(json.dumps({"event":"external_network_denied","host":str(host)})+"\n")
        raise PermissionError("SHOWCASE_LOCAL_ONLY blocks external network")
    def resolve(host,*args,**kwargs):
        if not allowed(host): deny(host)
        return _resolve(host,*args,**kwargs)
    def connect(sock,address):
        if sock.family in {socket.AF_INET,socket.AF_INET6} and not allowed(address[0]): deny(address[0])
        return _connect(sock,address)
    def connect_ex(sock,address):
        if sock.family in {socket.AF_INET,socket.AF_INET6} and not allowed(address[0]): deny(address[0])
        return _connect_ex(sock,address)
    socket.getaddrinfo=resolve
    socket.socket.connect=connect
    socket.socket.connect_ex=connect_ex
