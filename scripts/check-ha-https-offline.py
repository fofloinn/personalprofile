#!/usr/bin/env python3
"""Synthetic nginx integration check. Cached images only; no host ports or live data.

Run: python scripts/check-ha-https-offline.py
Creates two isolated Docker networks and disposable containers, removed in finally.
Only the explicitly listed checked-in proxy files are read. No .env/.local mounts.
"""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ha_https", ROOT / "scripts/setup-ha-https.py")
ha = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ha)

BACKEND = r'''
import base64, hashlib, json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self): self.do_GET()
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/":
            status = 401 if self.client_address[0] == os.environ["TRUSTED"] and self.headers.get("X-Forwarded-For") else 400
        elif path == "/api/websocket":
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            key = self.headers.get("Sec-WebSocket-Key", "")
            self.send_header("Sec-WebSocket-Accept", base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode())
            self.end_headers()
            return
        else:
            status = 200
        payload = json.dumps({"source": self.client_address[0], "forwarded": self.headers.get("X-Forwarded-For"),
                              "proto": self.headers.get("X-Forwarded-Proto"), "host": self.headers.get("Host"),
                              "admin": self.headers.get("X-Website-Admin")}).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "public, max-age=600")
        self.end_headers()
        self.wfile.write(payload)
import threading
threading.Thread(target=lambda: ThreadingHTTPServer(("0.0.0.0", 80), Handler).serve_forever(), daemon=True).start()
ThreadingHTTPServer((os.environ["LAN"], 8123), Handler).serve_forever()
'''

CLIENT = r'''
import hashlib, http.client, json, os, socket, ssl, sys
mode = sys.argv[1]
ctx = ssl.create_default_context(cafile="/fixture/certs/live/fearghal.fnl.life/fullchain.pem")
ctx.load_verify_locations("/fixture/certs/live/ha.fnl.life/fullchain.pem")
def request(host, port, path, method="GET", headers=None):
    sock = socket.create_connection((os.environ["PROXY"], port), timeout=5)
    if port != 8080:
        sock = ctx.wrap_socket(sock, server_hostname=host)
    supplied = {"Host": host, "Connection": "close", **(headers or {})}
    wire = method + " " + path + " HTTP/1.1\r\n" + "".join(k + ": " + v + "\r\n" for k,v in supplied.items()) + "\r\n"
    sock.sendall(wire.encode())
    try:
        reply = http.client.HTTPResponse(sock)
        reply.begin()
        result = (reply.status, dict(reply.getheaders()), reply.read() if reply.status != 101 else b"")
    except http.client.RemoteDisconnected:
        result = (0, {}, b"")
    sock.close()
    return result
def check(host, port, path, expected, method="GET", headers=None):
    try:
        result = request(host, port, path, method, headers)
    except Exception as error:
        raise AssertionError((mode, path, type(error).__name__)) from None
    assert result[0] == expected, (mode, path, result[0], expected)
    return result
check("fearghal.fnl.life", 8443, "/", 200)
check("fearghal.fnl.life", 8443, "/wp-admin/", 403)
check("fearghal.fnl.life", 8443, "/", 403, "POST")
check("fearghal.fnl.life", 8443, "/?rest_route=fixture", 403)
check("fearghal.fnl.life", 8444, "/wp-admin/", 200, "POST")
check("fearghal.fnl.life", 8080, "/", 301)
check("ha.fnl.life", 8080, "/?privacy-canary", 404)
check("ha.fnl.life", 8080, "/.well-known/acme-challenge/fixture", 200)
if mode == "off":
    # Default website certificate intentionally does not cover HA; route is also rejected.
    ctx.check_hostname = False
    check("ha.fnl.life", 8443, "/api/?privacy-canary", 0)
else:
    response = check("ha.fnl.life", 8443, "/api/?privacy-canary", 401,
                     headers={"X-Forwarded-For": "198.51.100.99", "X-Website-Admin": "1"})
    data = json.loads(response[2])
    assert data["source"] == os.environ["TRUSTED"], "proxy source changed"
    assert data["forwarded"] == os.environ["CLIENT"], "client spoofing allowed"
    assert data["proto"] == "https" and data["host"] == "ha.fnl.life"
    assert not data["admin"], "website private header leaked"
    assert response[1]["Cache-Control"] == "no-store"
    check("ha.fnl.life", 8443, "/auth/token", 200, "POST")
    check("ha.fnl.life", 8443, "/frontend_latest/fixture.js", 200)
    check("ha.fnl.life", 8443, "/api/websocket", 101, headers={
        "Connection": "Upgrade", "Upgrade": "websocket", "Sec-WebSocket-Key": "Zml4dHVyZS1vbmx5"})
    for path in ("/local", "/local/fixture", "/LOCAL/fixture", "/%6cocal/fixture", "/static/../local/fixture",
                 "/media/fixture", "/api/webhook/fixture", "/api/camera_proxy/fixture", "/api/image/serve/fixture",
                 "/api/media_player_proxy/fixture", "/api/tts_proxy/fixture", "/hacsfiles/fixture", "/api/config"):
        denied = check("ha.fnl.life", 8443, path, 404)
        assert denied[1]["Cache-Control"] == "no-store"
    # Confirms SNI used the separate HA certificate, not the website certificate.
    with ctx.wrap_socket(socket.create_connection((os.environ["PROXY"], 8443)), server_hostname="ha.fnl.life") as sock:
        print(hashlib.sha256(sock.getpeercert(binary_form=True)).hexdigest())
'''


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if result.returncode:
        # Only synthetic operations; still don't dump full diagnostic payloads.
        if "/fixture/client.py" in args and result.stderr:
            print("Synthetic client failure: " + result.stderr.strip().splitlines()[-1])
        raise RuntimeError("Isolated Docker operation failed: " + args[0])
    return result.stdout.strip()


def ip(container, network):
    data = json.loads(docker("inspect", container))[0]
    return data["NetworkSettings"]["Networks"][network]["IPAddress"]


def certificate(root, hostname):
    directory = root / "certs/live" / hostname
    directory.mkdir(parents=True, exist_ok=True)
    docker("run", "--rm", "--pull", "never", "--network", "none",
           "--mount", f"type=bind,source={directory},target=/certificate",
           "python:3.14-slim", "openssl", "req", "-x509", "-newkey", "rsa:2048",
           "-nodes", "-days", "1", "-subj", "/CN=" + hostname, "-addext", "subjectAltName=DNS:" + hostname,
           "-keyout", "/certificate/privkey.pem", "-out", "/certificate/fullchain.pem")


def check_compose(root):
    # Explicit synthetic env file; never resolve the real checkout's .env.
    (root / "compose.production.yaml").write_text((ROOT / "compose.production.yaml").read_text())
    (root / "synthetic.env").write_text(
        "DB_NAME=fixture\nDB_USER=fixture\nDB_PASSWORD=fixture-not-secret\nDB_ROOT_PASSWORD=fixture-not-secret\n")
    settings = ha.validate_addresses("192.168.50.10", "172.30.250.0/29")
    (root / "ha-compose.json").write_text(json.dumps(ha.compose_override(settings)))
    base = ["compose", "--project-directory", str(root), "--env-file", str(root / "synthetic.env"),
            "-f", str(root / "compose.production.yaml")]
    for enabled in (False, True):
        files = ["-f", str(root / "ha-compose.json")] if enabled else []
        config = json.loads(docker(*base, *files, "config", "--format", "json"))
        services = config["services"]
        assert set(services["proxy"]["networks"]) == ({"web", "ha_proxy"} if enabled else {"web"})
        assert set(services["wordpress"]["networks"]) == {"web", "database"}
        assert set(services["database"]["networks"]) == {"database"}
        assert all("ports" not in services[s] for s in ("wordpress", "database"))
        ports = services["proxy"]["ports"]
        assert len(ports) == 3
        assert next(p for p in ports if p["target"] == 8444)["host_ip"] == "127.0.0.1"
        if enabled:
            assert services["proxy"]["networks"]["ha_proxy"]["gw_priority"] == 100
    print("PASS: default/optional production Compose renders, dedicated gateway priority, no extra port or service exposure")


def main():
    prefix = "ha-offline-" + uuid.uuid4().hex[:10]
    web, trusted = prefix + "-web", prefix + "-trusted"
    backend, proxy = prefix + "-backend", prefix + "-proxy"
    networks, containers = [], []
    with tempfile.TemporaryDirectory(prefix="ha-https-fixture-") as temporary:
        root = Path(temporary)
        try:
            check_compose(root)
            for network in (web, trusted):
                docker("network", "create", "--internal", network)
                networks.append(network)
            for hostname in ("fearghal.fnl.life", "ha.fnl.life"):
                certificate(root, hostname)
            (root / "enabled").mkdir()
            (root / "acme/.well-known/acme-challenge").mkdir(parents=True)
            (root / "acme/.well-known/acme-challenge/fixture").write_text("synthetic")
            for filename in ("nginx.conf", "proxy.conf", "proxy-entrypoint.sh"):
                shutil.copyfile(ROOT / "docker/nginx" / filename, root / filename)
            (root / "backend.py").write_text(BACKEND)
            (root / "client.py").write_text(CLIENT)

            # Start proxy idle to allocate both interfaces; then run the real entrypoint.
            docker("run", "-d", "--pull", "never", "--name", proxy, "--network", web,
                   "--read-only", "--tmpfs", "/var/cache/nginx", "--tmpfs", "/var/run", "--tmpfs", "/tmp",
                   "--security-opt", "no-new-privileges:true", "--cap-drop", "ALL",
                   "--cap-add", "CHOWN", "--cap-add", "SETUID", "--cap-add", "SETGID",
                   "--mount", f"type=bind,source={root / 'nginx.conf'},target=/etc/nginx/nginx.conf,readonly",
                   "--mount", f"type=bind,source={root / 'proxy.conf'},target=/etc/nginx/website-proxy.conf,readonly",
                   "--mount", f"type=bind,source={root / 'proxy-entrypoint.sh'},target=/entrypoint.sh,readonly",
                   "--mount", f"type=bind,source={root / 'enabled'},target=/etc/nginx/ha-enabled,readonly",
                   "--mount", f"type=bind,source={root / 'certs'},target=/etc/letsencrypt,readonly",
                   "--mount", f"type=bind,source={root / 'acme'},target=/var/www/acme,readonly",
                   "--entrypoint", "sh", "nginx:stable-alpine", "-c",
                   "while [ ! -f /etc/nginx/ha-enabled/start ]; do sleep 1; done; exec sh /entrypoint.sh")
            containers.append(proxy)
            docker("network", "connect", trusted, proxy)
            source = ip(proxy, trusted)
            docker("run", "-d", "--pull", "never", "--name", backend, "--network", web,
                   "--network-alias", "wordpress",
                   "--mount", f"type=bind,source={root},target=/fixture,readonly",
                   "-e", "TRUSTED=" + source, "-e", "PROXY=" + ip(proxy, web),
                   "python:3.14-slim", "sleep", "600")
            containers.append(backend)
            docker("network", "connect", trusted, backend)
            # Mock private backend on the dedicated bridge. This verifies binding,
            # not a claim about the real NUC's host firewall/reverse-path filtering.
            lan = ip(backend, trusted)
            client = ip(backend, web)
            def client_check(mode):
                return docker("exec", "-e", "LAN=" + lan, "-e", "CLIENT=" + client,
                              backend, "python", "/fixture/client.py", mode)
            docker("exec", "-d", "-e", "LAN=" + lan, backend, "python", "/fixture/backend.py")
            (root / "enabled/probe.conf").write_text(ha.probe({"backend": lan, "proxy": source}))
            (root / "enabled/start").write_text("synthetic")
            time.sleep(2)
            docker("exec", proxy, "nginx", "-t")
            probe = subprocess.run(["docker", "exec", proxy, "wget", "-S", "-O", "/dev/null",
                                    "-T", "10", "http://127.0.0.1:18081/api/"], capture_output=True, text=True)
            statuses = re.findall(r"(?m)^[ \t]*HTTP/\d(?:\.\d)?[ \t]+(\d{3})\b", probe.stderr)
            assert statuses == ["401"], ("synthetic prepare probe status", statuses)
            client_check("off")
            print("PASS: default-off HA, HTTP ACME, website POST/admin blocks and private admin behavior")
            print("PASS: actual loopback-only nginx prepare probe returns forwarded 401 with BusyBox wget")

            (root / "enabled/upstream.inc").write_text(ha.upstream({"backend": lan, "proxy": source}))
            shutil.copyfile(ROOT / "docker/nginx/ha-proxy.conf.template", root / "enabled/public.conf")
            docker("exec", proxy, "nginx", "-t")
            docker("exec", proxy, "nginx", "-s", "reload")
            time.sleep(2)
            first = client_check("on")
            print("PASS: real TLS, exact bound source across two interfaces, forwarded 401, spoof protection, WebSocket 101")
            print("PASS: sharing/normalized local paths denied, POST auth allowed, no-store headers, website unchanged")

            # Actual unchanged 60s entrypoint watcher, synthetic second HA cert only.
            certificate(root, "ha.fnl.life")
            renewed = False
            for _ in range(15):
                time.sleep(5)
                try:
                    current = client_check("on")
                    if first != current:
                        renewed = True
                        break
                except RuntimeError:
                    # New trust file was written, but nginx may still serve the old cert.
                    continue
            assert renewed, "Optional certificate watcher did not reload within 75 seconds"
            print("PASS: HA-only certificate rotation automatically reloaded; website certificate still valid")
            logs = subprocess.run(["docker", "logs", proxy], capture_output=True, text=True)
            # Inspect actual entrypoint/nginx stdout/stderr, never print log bodies.
            config = docker("exec", proxy, "nginx", "-T")
            assert "access_log off;" in config and "error_log /dev/null;" in config
            assert "privacy-canary" not in logs.stdout + logs.stderr
            (root / "enabled/public.conf").unlink()
            docker("restart", "--time", "10", proxy)
            time.sleep(2)
            client_check("off")
            print("PASS: disabling HA restores default-off routing without changing website routes")
        finally:
            for container in reversed(containers):
                subprocess.run(["docker", "rm", "-f", container], capture_output=True)
            for network in reversed(networks):
                subprocess.run(["docker", "network", "rm", network], capture_output=True)
    print("Offline fixtures removed; no host ports, ACME requests, live state or vendor access used.")


if __name__ == "__main__":
    main()
