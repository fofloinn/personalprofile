#!/usr/bin/env python3
"""Optional Linux-only HA HTTPS preparation/activation. No HA private-state reads.

Only stdlib; subprocess output is captured and never echoed (can contain secrets).
Run on the NUC, not a developer workstation. See docker/HOME_ASSISTANT_HTTPS.md.
"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
CONFIG = LOCAL / "ha-nginx"
STATE = LOCAL / "ha-settings.json"
OVERLAY = LOCAL / "ha-compose.json"
PRIVATE = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


class SetupError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise SetupError(message)


def run(args, *, ok=True):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if ok:
        require(result.returncode == 0, "Command failed; output withheld for privacy. No activation approved.")
    return result


def compose(*args, ok=True):
    return run(["bash", "scripts/production-compose.sh", *args], ok=ok)


def private_write(path, content):
    require(not path.is_symlink(), "Refusing a symlinked configuration file.")
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        # nginx drops DAC_OVERRIDE: its root master must read snippets owned by
        # the deployment user. The unmounted .local parent remains owner-only.
        if path.parent == CONFIG:
            os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def confirm(message):
    require(input(message + "\nType YES to confirm: ") == "YES", "Operator gate not confirmed.")


def validate_addresses(backend, subnet):
    try:
        address = ipaddress.IPv4Address(backend)
        network = ipaddress.IPv4Network(subnet, strict=True)
    except ValueError:
        raise SetupError("Use a reserved RFC1918 IPv4 address and canonical private IPv4 subnet.") from None
    require(any(address in n for n in PRIVATE), "HA must bind its reserved LAN IPv4, not loopback/host-gateway.")
    require(any(network.subnet_of(n) for n in PRIVATE) and 24 <= network.prefixlen <= 29,
            "Choose a private /24 through /29 dedicated subnet.")
    require(address not in network, "HA LAN address must not be in the dedicated Docker subnet.")
    return {"backend": str(address), "subnet": str(network),
            "gateway": str(network.network_address + 1), "proxy": str(network.network_address + 2)}


def check_network(settings):
    """Fail closed on visible host/Docker overlaps; operator also checks offline VPNs."""
    network = ipaddress.ip_network(settings["subnet"])
    addresses = json.loads(run(["ip", "-j", "-4", "address", "show"]).stdout)
    require(any(a.get("local") == settings["backend"] for i in addresses for a in i.get("addr_info", [])),
            "HA's specified LAN address is not assigned to this host.")
    routes = json.loads(run(["ip", "-j", "-4", "route", "show", "table", "all"]).stdout)
    for route in routes:
        destination = route.get("dst", "default")
        if destination == "default":
            continue
        require(not network.overlaps(ipaddress.ip_network(destination, strict=False)),
                "Dedicated subnet overlaps a host route. Choose another unused subnet.")
    ids = run(["docker", "network", "ls", "-q"]).stdout.split()
    if ids:
        networks = json.loads(run(["docker", "network", "inspect", *ids]).stdout)
        for item in networks:
            for pool in item.get("IPAM", {}).get("Config", []) or []:
                other = ipaddress.ip_network(pool["Subnet"])
                require(other.version != 4 or not network.overlaps(other),
                        "Dedicated subnet overlaps an existing Docker network.")


def upstream(settings):
    return f"""# Generated privately; source is stable even on a multi-interface proxy.
proxy_pass http://{settings['backend']}:8123;
proxy_bind {settings['proxy']};
proxy_http_version 1.1;
proxy_set_header Host ha.fnl.life;
proxy_set_header X-Forwarded-Host ha.fnl.life;
proxy_set_header X-Forwarded-Proto https;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection $ha_connection;
proxy_set_header X-Website-Admin "";
proxy_cache off;
proxy_store off;
proxy_buffering off;
proxy_hide_header Cache-Control;
proxy_hide_header Expires;
proxy_connect_timeout 5s;
proxy_read_timeout 3600s;
proxy_send_timeout 60s;
"""


def ui_settings(settings):
    print("\nPRIVATE operator settings — do not paste this output into tickets or chat.")
    print("HA 2026.9.4: Settings > System > Network > HTTP server")
    print("Trust X-Forwarded-For: ON")
    print("Trusted proxies: ONLY " + settings["proxy"] + " (one IPv4, no subnet)")
    print("Preserve bind address " + settings["backend"] + ", port 8123; TLS stays OFF in HA.")
    print("IP banning: ON; failed login threshold: 5. Preserve MFA/auth providers.")
    print("Save restarts HA. Reconnect through the existing private path and CONFIRM within 5 minutes")
    print("or HA rolls back. Do not edit http YAML or .storage. Public HTTPS requires the separate enable gate.")


def probe(settings):
    return f"""server {{
    listen 127.0.0.1:18081;
    access_log off;
    error_log /dev/null;
    location = /api/ {{
        proxy_pass http://{settings['backend']}:8123;
        proxy_bind {settings['proxy']};
        proxy_set_header Host ha.fnl.life;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For 192.0.2.1;
        proxy_connect_timeout 5s;
        proxy_read_timeout 5s;
    }}
    location / {{ return 404; }}
}}
"""


def compose_override(settings):
    return {
        "services": {"proxy": {"networks": {"web": {}, "ha_proxy": {
            "ipv4_address": settings["proxy"], "gw_priority": 100}}}},
        "networks": {"ha_proxy": {"driver": "bridge", "ipam": {"config": [
            {"subnet": settings["subnet"], "gateway": settings["gateway"]}]}}},
    }


def prepare():
    version = compose("version", "--short").stdout.strip().lstrip("v")
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
    require(match and tuple(map(int, match.groups())) >= (2, 33, 1),
            "Docker Compose 2.33.1+ is required for the dedicated interface's gateway priority.")
    if STATE.exists() and OVERLAY.exists():
        require(not (CONFIG / "public.conf").exists(), "Already public; use check or disable.")
        saved = load_settings()
        require((CONFIG / "probe.conf").is_file(), "Prepared probe is missing. Restore the private configuration.")
        compose("config", "--quiet")
        compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", "60", "proxy")
        ui_settings(saved)
        return
    require(not OVERLAY.exists() and not STATE.exists(),
            "Already prepared. Use settings, enable or disable; do not replace the trusted source IP.")
    settings = validate_addresses(input("HA reserved LAN IPv4 (existing bind_address): ").strip(),
                                  input("Unused dedicated Docker IPv4 subnet (no default): ").strip())
    check_network(settings)
    ui_settings(settings)
    confirm("I checked ALL LAN, Docker and VPN networks (including disconnected VPNs); this subnet is unused.\n"
            "Host firewall permits ONLY this proxy IP to HA:8123, never bridge/vendor ports.\n"
            "I am on the Linux NUC and have an independent private HA/SSH recovery path.")
    # No new port publication; only nginx joins this network, never WordPress/database/Eufy.
    private_write(STATE, json.dumps(settings, indent=2) + "\n")
    private_write(OVERLAY, json.dumps(compose_override(settings), indent=2) + "\n")
    # This probe is reachable ONLY inside the nginx container's network namespace.
    private_write(CONFIG / "probe.conf", probe(settings))
    compose("config", "--quiet")
    compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", "60", "proxy")
    ui_settings(settings)


def load_settings():
    require(STATE.is_file(), "Run prepare first.")
    saved = json.loads(STATE.read_text())
    expected = validate_addresses(saved["backend"], saved["subnet"])
    require(saved == expected, "Prepared settings changed; restore the reviewed private configuration.")
    return saved


def backend_check():
    # BusyBox wget reports error statuses on stderr. Capture only, never print headers/body.
    result = compose("exec", "-T", "proxy", "wget", "-S", "-O", "/dev/null",
                     "-T", "10", "http://127.0.0.1:18081/api/", ok=False)
    # BusyBox repeats the status in "wget: server returned error: HTTP/...".
    # Count actual header lines only; redirects must still be rejected.
    statuses = re.findall(r"(?m)^[ \t]*HTTP/\d(?:\.\d)?[ \t]+(\d{3})\b", result.stderr)
    require(statuses == ["401"],
            "Forwarded backend probe must return exactly 401 (400 means proxy trust is wrong). Do not activate.")


def reload_proxy():
    compose("exec", "-T", "proxy", "nginx", "-t")
    compose("exec", "-T", "proxy", "nginx", "-s", "reload")


def public_check():
    # nginx reload returns before the new workers accept connections.
    time.sleep(1)
    for path, expected in (("/api/", "401"), ("/local/privacy-probe", "404"),
                           ("/api/webhook/privacy-probe", "404"), ("/api/image/serve/privacy-probe", "404")):
        result = run(["curl", "--noproxy", "*", "--silent", "--max-time", "15",
                      "--output", "/dev/null", "--write-out", "%{http_code}",
                      "--resolve", "ha.fnl.life:443:127.0.0.1", "https://ha.fnl.life" + path])
        require(result.stdout == expected, "HTTPS privacy/authentication check failed.")


def disable():
    try:
        (CONFIG / "public.conf").unlink(missing_ok=True)
        reload_proxy()
        # Reload alone leaves old authenticated WebSockets alive. Restart ONLY
        # nginx to revoke them; WordPress/database and all HA/vendor containers stay up.
        compose("restart", "--no-deps", "--timeout", "10", "proxy")
        compose("up", "-d", "--no-deps", "--wait", "--wait-timeout", "60", "proxy")
    except BaseException:
        # Interruptions must also close old workers/WebSockets, including when
        # disable() is itself rolling back a failed activation.
        compose("stop", "proxy")
        raise
    print("Public HA route disabled and connections closed. Website proxy restarted; cert/network retained.")


def enable():
    saved = load_settings()
    require(not (CONFIG / "public.conf").exists(), "Already enabled. Use check or disable; activation is not a rerun.")
    ui_settings(saved)
    confirm("I saved AND confirmed HA HTTP settings within 5 minutes; private access still works.\n"
            "MFA and strong unique credentials are enabled; no trusted-network/bypass auth is configured.\n"
            "I audited unauthenticated login/static content for PII; no private custom assets are in /static.\n"
            "No devices are shared with Google. I accept exposing the login/OAuth endpoint and authenticated HA\n"
            "(including authenticated WebSocket data). HTTPS cannot guarantee zero PII exposure.")
    backend_check()
    confirm("DNS ha.fnl.life CNAME points to the existing website, including correct public IPv4/IPv6 routing.\n"
            "Only existing 80/443 forwards reach nginx; 8123/vendor ports remain private.\n"
            "Issue a SEPARATE ha.fnl.life certificate through the running HTTP webroot, without stopping the website?\n"
            "I accept Let's Encrypt terms and understand this hostname enters public certificate transparency logs.")
    # Reuse the existing ACME account; never prompt for/read/print account identifiers.
    # --cert-name prevents expanding/replacing the website's certificate.
    compose("run", "--rm", "--no-deps", "--entrypoint", "certbot", "certbot",
            "certonly", "--webroot", "-w", "/var/www/acme", "--non-interactive",
            "--agree-tos", "--keep-until-expiring", "--cert-name", "ha.fnl.life", "-d", "ha.fnl.life")
    backend_check()
    try:
        private_write(CONFIG / "upstream.inc", upstream(saved))
        private_write(CONFIG / "public.conf", (ROOT / "docker/nginx/ha-proxy.conf.template").read_text())
        reload_proxy()
        public_check()
    except BaseException:
        disable()
        raise
    print("HTTPS local certificate/auth/privacy probes passed. No Google linking or HA device changes made.")
    print("Next: repeat the documented checks from an external network without credentials; do not share response bodies.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "settings", "enable", "check", "disable"))
    args = parser.parse_args()
    require(sys.platform == "linux", "Run ONLY on the Linux NUC; this is not a workstation publisher.")
    require(os.getuid() != 0, "Run as the deployment user, not root/sudo.")
    def interrupted(_signum, _frame):
        raise SetupError("Interrupted; activation was not completed.")
    signal.signal(signal.SIGTERM, interrupted)
    os.umask(0o077)
    require(not LOCAL.is_symlink() and not CONFIG.is_symlink(), "Private directories must not be symlinks.")
    LOCAL.mkdir(mode=0o700, exist_ok=True)
    CONFIG.mkdir(mode=0o700, exist_ok=True)
    require(LOCAL.stat().st_uid == os.getuid(), "Use the private directory's owner, not sudo.")
    require(not (LOCAL.stat().st_mode & 0o077), "Set .local permissions to 700 before continuing.")
    # Only this non-secret snippets directory is mounted into the restricted
    # nginx container; .local itself, settings and the override are not mounted.
    CONFIG.chmod(0o755)
    for path in (STATE, OVERLAY, CONFIG / "probe.conf", CONFIG / "public.conf", CONFIG / "upstream.inc"):
        require(not path.is_symlink(), "Refusing symlinked optional configuration.")
    # Serialise this script's prepare/enable/disable operations. Never share the
    # production lifecycle with another operator while this gate is running.
    import fcntl
    lock_fd = os.open(LOCAL / "ha-setup.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SetupError("Another HTTPS setup operation is running.") from None
    if args.action == "prepare":
        prepare()
    elif args.action == "settings":
        ui_settings(load_settings())
    elif args.action == "enable":
        enable()
    elif args.action == "disable":
        disable()
    else:
        load_settings()
        try:
            backend_check()
            public_check()
        except BaseException:
            if (CONFIG / "public.conf").exists():
                disable()
            raise
        print("Certificate, exact-source forwarded authentication and denied sharing probes passed.")


if __name__ == "__main__":
    try:
        main()
    except SetupError as error:
        print("STOP: " + str(error), file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, KeyError, EOFError, KeyboardInterrupt):
        # Exception values, commands and response bodies may contain private inputs.
        print("STOP: setup did not complete. Details withheld for privacy. Review the documented gates;\n"
              "use 'settings' for prepared values, or 'disable' to withdraw public HA.", file=sys.stderr)
        sys.exit(1)
