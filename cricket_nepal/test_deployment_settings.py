import json
import os
import subprocess
import sys
from unittest import TestCase


class SecureDeploymentSettingsTests(TestCase):
    def load_settings(self, **overrides):
        environment = os.environ.copy()
        environment.update(
            {
                "DJANGO_SECRET_KEY": "test-only-secret-key-not-used-for-deployment",
                "DJANGO_SECURE_DEPLOYMENT": "true",
                "DJANGO_DEBUG": "false",
                "DJANGO_ALLOWED_HOSTS": "example.test",
                **overrides,
            }
        )
        return subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json; import config.settings as s; "
                    "print(json.dumps({"
                    "'ssl_redirect': s.SECURE_SSL_REDIRECT, "
                    "'proxy_header': s.SECURE_PROXY_SSL_HEADER, "
                    "'session_secure': s.SESSION_COOKIE_SECURE, "
                    "'csrf_secure': s.CSRF_COOKIE_SECURE, "
                    "'hsts': s.SECURE_HSTS_SECONDS"
                    "}))"
                ),
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_secure_deployment_enables_https_protections(self):
        result = self.load_settings()
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(result.stdout)
        self.assertTrue(settings["ssl_redirect"])
        self.assertEqual(settings["proxy_header"], ["HTTP_X_FORWARDED_PROTO", "https"])
        self.assertTrue(settings["session_secure"])
        self.assertTrue(settings["csrf_secure"])
        self.assertGreater(settings["hsts"], 0)

    def test_secure_deployment_rejects_debug_and_unsafe_hosts(self):
        for overrides in (
            {"DJANGO_DEBUG": "true"},
            {"DJANGO_ALLOWED_HOSTS": ""},
            {"DJANGO_ALLOWED_HOSTS": "*"},
            {"DJANGO_ALLOWED_HOSTS": "example.test,*"},
        ):
            with self.subTest(overrides=overrides):
                result = self.load_settings(**overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ValueError", result.stderr)
