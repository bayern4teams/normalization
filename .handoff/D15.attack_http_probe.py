"""D15 HTTP probes against a real uvicorn (raw sockets). Run:
  NORM_BIND_ADDR=192.168.1.5 uv run --python 3.12 python .handoff/D15.attack_http_probe.py"""
import asyncio, socket, threading, time
import uvicorn
from normapi.app import create_app

app = create_app()
cfg = uvicorn.Config(app, host="127.0.0.1", port=18099, log_level="error")
srv = uvicorn.Server(cfg)
threading.Thread(target=srv.run, daemon=True).start()
time.sleep(4)

def raw(headers: list[str], path="/openapi.json", src=None):
    s = socket.socket()
    if src: s.bind((src, 0))
    s.connect(("127.0.0.1", 18099))
    s.sendall((f"GET {path} HTTP/1.1\r\n" + "".join(h + "\r\n" for h in headers) + "Connection: close\r\n\r\n").encode("latin-1"))
    data = b""
    while chunk := s.recv(65536):
        data += chunk
    return data.split(b"\r\n", 1)[0].decode()
cases = {
 "localhost": ["Host: localhost"],
 "localhost:8000": ["Host: localhost:8000"],
 "LOCALHOST": ["Host: LOCALHOST"],
 "127.0.0.1": ["Host: 127.0.0.1"],
 "[::1]": ["Host: [::1]"],
 "[::1]:8000": ["Host: [::1]:8000"],
 "bind addr": ["Host: 192.168.1.5"],
 "localhost.": ["Host: localhost."],
 "evil.com": ["Host: evil.com"],
 "localhost.evil.com": ["Host: localhost.evil.com"],
 "dup localhost then evil": ["Host: localhost", "Host: evil.com"],
 "dup evil then localhost": ["Host: evil.com", "Host: localhost"],
 "localhost@evil.com": ["Host: localhost@evil.com"],
 "localhost:80@evil": ["Host: localhost:80@evil.com"],
 "localhost, evil": ["Host: localhost, evil.com"],
 "no host (HTTP/1.1)": [],
 "XFF 10.0.0.1 from loopback": ["Host: localhost", "X-Forwarded-For: 10.0.0.1"],
 "XFF 8.8.8.8 from loopback": ["Host: localhost", "X-Forwarded-For: 8.8.8.8"],
 "Forwarded for 8.8.8.8": ["Host: localhost", "Forwarded: for=8.8.8.8"],
 "X-Forwarded-Host evil": ["Host: localhost", "X-Forwarded-Host: evil.com"],
 "Host with tab": ["Host: localhost\t"],
 "0.0.0.0": ["Host: 0.0.0.0"],
}
for name, h in cases.items():
    try: print(f"{name:32s} {raw(h)}")
    except Exception as e: print(f"{name:32s} EXC {type(e).__name__}")
# absolute-form request target with hostile host
try: print("abs-form http://evil.com/       ", raw(["Host: localhost"], path="http://evil.com/openapi.json"))
except Exception as e: print("abs-form EXC", e)
# peer from 127.0.0.2 (still loopback)
print("peer 127.0.0.2                  ", raw(["Host: localhost"], src="127.0.0.2"))
srv.should_exit = True
