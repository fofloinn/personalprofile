"""Offline stdlib tests. Never read .env, real HA state, or run ACME."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ha_https", ROOT / "scripts/setup-ha-https.py")
ha = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ha)


class HttpsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.local = self.root / ".local"
        self.config = self.local / "ha-nginx"
        self.config.mkdir(parents=True)
        (self.root / "docker/nginx").mkdir(parents=True)
        (self.root / "docker/nginx/ha-proxy.conf.template").write_text(
            (ROOT / "docker/nginx/ha-proxy.conf.template").read_text())
        for name, value in (("ROOT", self.root), ("LOCAL", self.local), ("CONFIG", self.config),
                            ("STATE", self.local / "ha-settings.json"), ("OVERLAY", self.local / "ha-compose.json")):
            p = patch.object(ha, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.saved = ha.validate_addresses("192.168.50.10", "172.30.250.0/29")
        self.calls = []

    def prepared(self):
        ha.private_write(ha.STATE, json.dumps(self.saved))
        ha.private_write(ha.OVERLAY, "{}")
        ha.private_write(self.config / "probe.conf", "# synthetic")

    def fake_compose(self, *args, ok=True):
        self.calls.append(args)
        if args == ("version", "--short"):
            return subprocess.CompletedProcess(args, 0, "2.33.1", "")
        if "wget" in args:
            return subprocess.CompletedProcess(args, 1, "", "  HTTP/1.1 401 Unauthorized\n")
        return subprocess.CompletedProcess(args, 0, "", "")

    def test_addresses_reject_loopback_public_and_overlap(self):
        for backend, subnet in (("127.0.0.1", "172.30.250.0/29"),
                                ("0.0.0.0", "172.30.250.0/29"),
                                ("192.0.2.10", "172.30.250.0/29"),
                                ("172.30.250.3", "172.30.250.0/29"),
                                ("192.168.50.10", "172.30.250.1/29"),
                                ("192.168.50.10", "0.0.0.0/0")):
            with self.subTest(backend=backend, subnet=subnet), self.assertRaises(ha.SetupError):
                ha.validate_addresses(backend, subnet)

    def test_stable_source_is_second_host(self):
        self.assertEqual(self.saved["proxy"], "172.30.250.2")
        self.assertEqual(self.saved["gateway"], "172.30.250.1")

    @unittest.skipUnless(os.name == "posix", "POSIX modes require Linux")
    def test_nginx_can_read_exported_snippets_but_settings_stay_private(self):
        ha.private_write(ha.STATE, "{}")
        ha.private_write(self.config / "probe.conf", "# synthetic")
        self.assertEqual(ha.STATE.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.config / "probe.conf").stat().st_mode & 0o777, 0o644)

    def test_route_docker_and_host_ownership_gates(self):
        def result(value):
            return subprocess.CompletedProcess([], 0, json.dumps(value), "")
        addresses = [{"addr_info": [{"local": self.saved["backend"]}]}]
        for replies in (
            [result([])],
            [result(addresses), result([{"dst": "172.30.0.0/16"}])],
            [result(addresses), result([]), subprocess.CompletedProcess([], 0, "fixture", ""),
             result([{"IPAM": {"Config": [{"Subnet": "172.30.250.0/24"}]}}])],
        ):
            with self.subTest(replies=len(replies)), patch.object(ha, "run", side_effect=replies), self.assertRaises(ha.SetupError):
                ha.check_network(self.saved)

    def test_prepare_is_default_off_and_only_attaches_proxy(self):
        with patch("builtins.input", side_effect=[self.saved["backend"], self.saved["subnet"], "YES"]), \
                patch.object(ha, "check_network"), patch.object(ha, "compose", side_effect=self.fake_compose), \
                patch.object(ha, "ui_settings"):
            ha.prepare()
        self.assertFalse((self.config / "public.conf").exists())
        overlay = json.loads(ha.OVERLAY.read_text())
        self.assertEqual(set(overlay["services"]), {"proxy"})
        self.assertEqual(set(overlay["services"]["proxy"]["networks"]), {"web", "ha_proxy"})
        self.assertEqual(overlay["services"]["proxy"]["networks"]["ha_proxy"]["gw_priority"], 100)
        self.assertNotIn("ports", overlay["services"]["proxy"])
        probe = (self.config / "probe.conf").read_text()
        self.assertIn("listen 127.0.0.1:18081", probe)
        self.assertIn("proxy_bind " + self.saved["proxy"], probe)
        self.assertIn("proxy_pass http://" + self.saved["backend"] + ":8123", probe)
        self.assertFalse(any("certbot" in c for c in self.calls))

    def test_prepare_denied_gate_writes_no_configuration(self):
        with patch("builtins.input", side_effect=[self.saved["backend"], self.saved["subnet"], "NO"]), \
                patch.object(ha, "check_network"), patch.object(ha, "compose", side_effect=self.fake_compose), \
                patch.object(ha, "ui_settings"), \
                self.assertRaises(ha.SetupError):
            ha.prepare()
        self.assertFalse(ha.OVERLAY.exists())
        self.assertFalse(ha.STATE.exists())

    def test_old_compose_rejected_before_preparation(self):
        with patch.object(ha, "compose", return_value=subprocess.CompletedProcess([], 0, "2.30.0", "")), \
                self.assertRaises(ha.SetupError):
            ha.prepare()
        self.assertFalse(ha.OVERLAY.exists())

    def test_prepare_resume_preserves_source_and_stays_off(self):
        self.prepared()
        before = ha.STATE.read_bytes()
        with patch.object(ha, "compose", side_effect=self.fake_compose), patch.object(ha, "ui_settings"):
            ha.prepare()
        self.assertEqual(ha.STATE.read_bytes(), before)
        self.assertFalse((self.config / "public.conf").exists())

    def test_probe_requires_exact_401(self):
        for status in ("200 OK", "400 Bad Request", "301 Moved", "403 Forbidden", ""):
            with self.subTest(status=status), patch.object(ha, "compose", return_value=subprocess.CompletedProcess(
                    [], 1, "", "HTTP/1.1 " + status)), self.assertRaises(ha.SetupError):
                ha.backend_check()
        with patch.object(ha, "compose", side_effect=self.fake_compose):
            ha.backend_check()

    def test_busybox_duplicate_error_text_not_counted_as_second_response(self):
        with patch.object(ha, "compose", return_value=subprocess.CompletedProcess([], 1, "",
                "  HTTP/1.1 401 Unauthorized\nwget: server returned error: HTTP/1.1 401 Unauthorized\n")):
            ha.backend_check()
        with patch.object(ha, "compose", return_value=subprocess.CompletedProcess([], 1, "",
                "  HTTP/1.1 302 Found\n  HTTP/1.1 401 Unauthorized\n")), self.assertRaises(ha.SetupError):
            ha.backend_check()

    def test_privacy_mfa_gate_prevents_acme_and_publication(self):
        self.prepared()
        with patch.object(ha, "ui_settings"), patch("builtins.input", return_value="NO"), \
                patch.object(ha, "compose", side_effect=self.fake_compose), self.assertRaises(ha.SetupError):
            ha.enable()
        self.assertEqual(self.calls, [])
        self.assertFalse((self.config / "public.conf").exists())

    def test_failed_backend_prevents_acme_and_publication(self):
        self.prepared()
        with patch.object(ha, "ui_settings"), patch.object(ha, "confirm"), \
                patch.object(ha, "compose", side_effect=self.fake_compose), \
                patch.object(ha, "backend_check", side_effect=ha.SetupError("fixture")), self.assertRaises(ha.SetupError):
            ha.enable()
        self.assertEqual(self.calls, [])
        self.assertFalse((self.config / "public.conf").exists())

    def test_acme_consent_gate_prevents_publication(self):
        self.prepared()
        with patch.object(ha, "ui_settings"), patch.object(ha, "confirm", side_effect=[None, ha.SetupError("fixture")]), \
                patch.object(ha, "compose", side_effect=self.fake_compose), self.assertRaises(ha.SetupError):
            ha.enable()
        self.assertFalse(any("certbot" in c for c in self.calls))
        self.assertFalse((self.config / "public.conf").exists())

    def test_enable_separate_webroot_cert_no_stop_no_google_changes(self):
        self.prepared()
        with patch.object(ha, "ui_settings"), patch.object(ha, "confirm"), \
                patch.object(ha, "compose", side_effect=self.fake_compose), patch.object(ha, "public_check"):
            ha.enable()
        certificate = next(c for c in self.calls if "certonly" in c)
        self.assertIn("--webroot", certificate)
        self.assertIn("--cert-name", certificate)
        self.assertEqual(certificate[-1], "ha.fnl.life")
        self.assertNotIn("--expand", certificate)
        self.assertFalse(any("stop" in c for c in self.calls))
        self.assertTrue((self.config / "public.conf").exists())
        self.assertEqual(sum("wget" in c for c in self.calls), 2)

    def test_acme_failure_remains_off(self):
        self.prepared()
        def fail(*args, **kwargs):
            if "certonly" in args:
                raise ha.SetupError("fixture")
            return self.fake_compose(*args, **kwargs)
        with patch.object(ha, "ui_settings"), patch.object(ha, "confirm"), \
                patch.object(ha, "compose", side_effect=fail), self.assertRaises(ha.SetupError):
            ha.enable()
        self.assertFalse((self.config / "public.conf").exists())

    def test_failed_postcheck_or_interrupt_withdraws_public_route(self):
        for failure in (ha.SetupError("fixture"), KeyboardInterrupt()):
            self.prepared()
            with self.subTest(failure=type(failure).__name__), patch.object(ha, "ui_settings"), \
                    patch.object(ha, "confirm"), patch.object(ha, "compose", side_effect=self.fake_compose), \
                    patch.object(ha, "public_check", side_effect=failure), self.assertRaises(type(failure)):
                ha.enable()
            self.assertFalse((self.config / "public.conf").exists())

    def test_failed_rollback_stops_proxy(self):
        ha.private_write(self.config / "public.conf", "fixture")
        failure = ha.SetupError("fixture")
        with patch.object(ha, "reload_proxy", side_effect=failure), \
                patch.object(ha, "compose", side_effect=self.fake_compose), self.assertRaises(ha.SetupError) as caught:
            ha.disable()
        self.assertIs(caught.exception, failure)
        self.assertIn(("stop", "proxy"), self.calls)
        self.assertFalse((self.config / "public.conf").exists())

    def test_interrupted_withdrawal_stops_proxy_and_preserves_error(self):
        for stage in ("reload", "restart", "up"):
            with self.subTest(stage=stage):
                self.calls.clear()
                ha.private_write(self.config / "public.conf", "fixture")
                interruption = KeyboardInterrupt()

                def compose(*args, **kwargs):
                    self.calls.append(args)
                    if args[0] == stage:
                        raise interruption
                    return subprocess.CompletedProcess(args, 0, "", "")

                with patch.object(ha, "reload_proxy", side_effect=interruption if stage == "reload" else None), \
                        patch.object(ha, "compose", side_effect=compose), self.assertRaises(KeyboardInterrupt) as caught:
                    ha.disable()
                self.assertIs(caught.exception, interruption)
                self.assertEqual(self.calls[-1], ("stop", "proxy"))
                self.assertFalse((self.config / "public.conf").exists())

    def test_interrupted_activation_rollback_stops_proxy(self):
        self.prepared()
        interruption = KeyboardInterrupt()
        with patch.object(ha, "ui_settings"), patch.object(ha, "confirm"), \
                patch.object(ha, "compose", side_effect=self.fake_compose), \
                patch.object(ha, "reload_proxy", side_effect=[None, interruption]), \
                patch.object(ha, "public_check", side_effect=ha.SetupError("fixture")), \
                self.assertRaises(KeyboardInterrupt) as caught:
            ha.enable()
        self.assertIs(caught.exception, interruption)
        self.assertEqual(self.calls[-1], ("stop", "proxy"))
        self.assertFalse((self.config / "public.conf").exists())

    def test_proxy_privacy_and_spoof_protection(self):
        content = ha.upstream(self.saved)
        self.assertIn("proxy_bind " + self.saved["proxy"], content)
        self.assertIn("proxy_set_header X-Forwarded-For $remote_addr;", content)
        self.assertNotIn("$proxy_add_x_forwarded_for", content)
        self.assertIn("proxy_cache off;", content)
        template = (ROOT / "docker/nginx/ha-proxy.conf.template").read_text()
        self.assertIn('Cache-Control "no-store"', template)
        self.assertIn("access_log off;", template)
        self.assertIn("error_log /dev/null;", template)
        self.assertIn("location / { return 404; }", template)
        self.assertNotIn("location /local", template)

    def test_disable_restarts_only_proxy_to_close_authenticated_websockets(self):
        ha.private_write(self.config / "public.conf", "fixture")
        with patch.object(ha, "compose", side_effect=self.fake_compose):
            ha.disable()
        self.assertIn(("restart", "--no-deps", "--timeout", "10", "proxy"), self.calls)
        self.assertFalse((self.config / "public.conf").exists())

    def test_default_configuration_has_no_public_ha_tls_or_host_port(self):
        base = (ROOT / "compose.production.yaml").read_text()
        nginx = (ROOT / "docker/nginx/nginx.conf").read_text()
        self.assertNotIn("ha_proxy:", base)
        self.assertNotIn("8123", base)
        self.assertNotIn("live/ha.fnl.life", nginx)
        self.assertIn('127.0.0.1:${ADMIN_PORT:-8443}:8444', base)
        self.assertIn('if ($request_method !~ ^(GET|HEAD)$) { return 403; }', nginx)

    def test_renewal_watches_all_lineages(self):
        entrypoint = (ROOT / "docker/nginx/proxy-entrypoint.sh").read_text()
        self.assertIn("/live/*/fullchain.pem", entrypoint)
        self.assertIn("/live/*/privkey.pem", entrypoint)
        self.assertIn("nginx -t && nginx -s reload", entrypoint)


if __name__ == "__main__":
    unittest.main()
