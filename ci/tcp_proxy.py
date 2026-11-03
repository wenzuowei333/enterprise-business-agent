"""CI-only fixed TCP ingress. No arbitrary upstream or CONNECT proxy."""
import argparse
import select
import socket
import socketserver

parser=argparse.ArgumentParser()
parser.add_argument("--target",choices=["api","test-postgres","test-redis"],required=True)
parser.add_argument("--port",type=int,required=True)
args=parser.parse_args()
expected={"api":8000,"test-postgres":5432,"test-redis":6379}
if args.port!=expected[args.target]:raise SystemExit("Unsupported fixed ingress port")
class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection((args.target,args.port),timeout=10) as upstream:
            upstream.settimeout(None)
            while True:
                ready,_,_=select.select([self.request,upstream],[],[],60)
                if not ready:return
                for source in ready:
                    data=source.recv(65536)
                    if not data:return
                    (upstream if source is self.request else self.request).sendall(data)
class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True
with Server(("0.0.0.0",args.port),Handler) as server:server.serve_forever()
