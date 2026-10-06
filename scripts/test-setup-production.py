"""Run with python3 on Linux; all Docker/network operations are mocked."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCKER = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MOCK_LOG"
case "$*" in
  "info"|"compose version") exit 0 ;;
  *"config --format json")
    printf '%s\n' '{"services":{"proxy":{"ports":[{"target":8080,"published":"80"},{"target":8443,"published":"443"},{"target":8444,"published":"8443"}]}},"volumes":{"database-data":{"name":"test_database"},"wordpress-data":{"name":"test_wordpress"},"wordpress-uploads":{"name":"test_uploads"}}}'
    ;;
  "volume inspect "*)
    case "${MOCK_VOLUMES:-existing}:$3" in
      existing:*|partial:test_database) exit 0 ;;
      *) exit 1 ;;
    esac
    ;;
  *".website-initial-content-pending"*) [[ ${MOCK_PENDING:-no} == yes ]] ;;
  *"compose.production.yaml ps -q") printf '' ;;
  "ps --no-trunc "*) printf '%s\n' "${MOCK_CONFLICT:-}" ;;
  *"test -s /etc/letsencrypt"*) [[ ${MOCK_CERT:-existing} == existing ]] ;;
  *"core is-installed") [[ ${MOCK_INSTALLED:-yes} == yes ]] ;;
  *"php -r "*)
    if [[ ${MOCK_DB_CONNECT:-yes} != yes ]]; then
      echo "Database connection failed: connection refused" >&2
      exit 1
    fi
    ;;
  *"wp --allow-root db query"*) echo "unexpected mysql client invocation" >&2; exit 88 ;;
  *" cp database:/tmp/site-backup.sql "*) printf 'backup\n' > "${@: -1}" ;;
  *) exit 0 ;;
esac
"""
CURL = r"""#!/usr/bin/env bash
case "$*" in
  *"--write-out"*) printf '%s' "${MOCK_ADMIN_STATUS:-403}" ;;
  *) exit 0 ;;
esac
"""


@unittest.skipUnless(os.name == "posix", "Bash orchestration tests require Linux")
class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "setup-production.sh").write_text(
            (ROOT / "setup-production.sh").read_text()
        )
        (self.root / ".env").write_text("DB_PASSWORD=unchanged\n")
        (self.root / "scripts").mkdir()
        (self.root / "scripts/issue-certificate.sh").write_text(
            'echo issued >> "$MOCK_LOG"\n'
        )
        tools = self.root / "tools"
        tools.mkdir()
        for name, content in [("docker", DOCKER), ("curl", CURL)]:
            path = tools / name
            path.write_text(content)
            path.chmod(0o700)
        self.env = {
            **os.environ,
            "PATH": f"{tools}:{os.environ['PATH']}",
            "MOCK_LOG": str(self.root / "commands.log"),
        }

    def run_setup(self, *args, **overrides):
        return subprocess.run(
            ["bash", str(self.root / "setup-production.sh"), *args],
            env={**self.env, **overrides},
            capture_output=True,
            text=True,
        )

    def test_existing_site_preserves_credentials_and_backs_up(self):
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / ".env").read_text(), "DB_PASSWORD=unchanged\n")
        self.assertEqual(len(list(self.root.glob("backups/*/database.sql"))), 1)
        self.assertNotIn("issued", (self.root / "commands.log").read_text())

    def test_fresh_host_does_not_need_volume_backups_or_seed_accounts(self):
        result = self.run_setup(MOCK_VOLUMES="absent", MOCK_INSTALLED="no")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("first WordPress setup", result.stdout)
        self.assertNotIn("No administrator account was created", result.stderr)
        self.assertFalse((self.root / "backups").exists())
        commands = (self.root / "commands.log").read_text()
        self.assertNotIn("mariadb-dump", commands)
        self.assertNotIn("search-replace", commands)

    def test_unfinished_fresh_install_can_be_restarted_without_backup(self):
        result = self.run_setup(MOCK_PENDING="yes", MOCK_INSTALLED="no")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("first WordPress setup", result.stdout)
        self.assertFalse((self.root / "backups").exists())
        self.assertNotIn("mariadb-dump", (self.root / "commands.log").read_text())

    def test_fresh_setup_checks_database_without_mysql_client(self):
        result = self.run_setup(MOCK_PENDING="yes", MOCK_INSTALLED="no")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = (self.root / "commands.log").read_text()
        self.assertIn("php -r", commands)
        self.assertNotIn("wp --allow-root db query", commands)

    def test_unavailable_database_reports_connection_failure(self):
        result = self.run_setup(
            MOCK_PENDING="yes", MOCK_INSTALLED="no", MOCK_DB_CONNECT="no"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WordPress cannot connect to its database", result.stderr)

    def test_partial_volumes_are_not_treated_as_a_fresh_install(self):
        result = self.run_setup(MOCK_VOLUMES="partial")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Only some site volumes exist", result.stderr)

    def test_restore_and_certificate(self):
        backup = self.root / "incoming"
        backup.mkdir()
        for name in ["database.sql", "wordpress.tgz", "uploads.tgz"]:
            (backup / name).write_text("fixture")
        result = self.run_setup(
            "--backup-dir", str(backup), "--email", "test@example.invalid",
            "--accept-terms", MOCK_VOLUMES="absent", MOCK_CERT="absent",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("issued", (self.root / "commands.log").read_text())

    def test_restore_refuses_existing_volumes(self):
        backup = self.root / "incoming"
        backup.mkdir()
        for name in ["database.sql", "wordpress.tgz", "uploads.tgz"]:
            (backup / name).write_text("fixture")
        result = self.run_setup("--backup-dir", str(backup))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No data was overwritten", result.stderr)

    def test_other_deployment_blocks_setup(self):
        result = self.run_setup(MOCK_CONFLICT="another-container")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Another running container", result.stderr)

    def test_certificate_requires_consent(self):
        result = self.run_setup("--email", "test@example.invalid", MOCK_CERT="absent")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--accept-terms", result.stderr)

    def test_failed_route_check_does_not_report_success(self):
        result = self.run_setup(MOCK_ADMIN_STATUS="200")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Public administration check failed", result.stderr)
        self.assertNotIn("Production is ready", result.stdout)


if __name__ == "__main__":
    unittest.main()
