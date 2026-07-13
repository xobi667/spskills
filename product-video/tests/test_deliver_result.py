import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deliver_result.py"
SPEC = importlib.util.spec_from_file_location("deliver_result", SCRIPT)
deliver_result = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(deliver_result)


def auth_payload(user_scopes=None, bot_ready=True):
    return {
        "verified": True,
        "identities": {
            "user": {
                "verified": True,
                "status": "ready",
                "tokenStatus": "valid",
                "openId": "test-dynamic-self-id",
                "userName": "Current User",
                "scope": user_scopes or [],
            },
            "bot": {
                "ready": bot_ready,
                "available": bot_ready,
                "verified": bot_ready,
            },
        },
    }


class DeliverResultTests(unittest.TestCase):
    def make_images(self, root):
        image_paths = []
        for index in range(1, 6):
            path = Path(root) / "source-{}.png".format(index)
            path.write_bytes(b"fake-png-" + str(index).encode("ascii"))
            image_paths.append(str(path))
        return image_paths

    def fake_completed(self, returncode=0, stdout="{}", stderr=""):
        return subprocess.CompletedProcess(["fake-lark-cli"], returncode, stdout, stderr)

    def test_probe_prefers_verified_user_with_required_scopes(self):
        payload = auth_payload(["im:message", "im:message.send_as_user"])

        def fake_run(argv, **kwargs):
            self.assertEqual(argv[1:], ["auth", "status", "--json", "--verify"])
            self.assertFalse(kwargs["shell"])
            self.assertEqual(kwargs["env"]["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"], "1")
            self.assertEqual(kwargs["env"]["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"], "1")
            return self.fake_completed(stdout=json.dumps(payload))

        with mock.patch.object(deliver_result.shutil, "which", return_value="fake-lark-cli"), mock.patch.object(
            deliver_result.subprocess, "run", side_effect=fake_run
        ):
            result = deliver_result.probe_identity()

        self.assertEqual(result["delivery_mode"], "user")
        self.assertEqual(result["user_open_id"], "test-dynamic-self-id")
        self.assertNotIn("token", json.dumps(result).lower())

    def test_probe_accepts_needs_refresh_when_server_verified_and_public_hides_identity(self):
        payload = auth_payload(["im:message", "im:message.send_as_user"])
        payload["identities"]["user"]["status"] = "needs_refresh"
        payload["identities"]["user"]["tokenStatus"] = "needs_refresh"
        with mock.patch.object(deliver_result.shutil, "which", return_value="fake-lark-cli"), mock.patch.object(
            deliver_result.subprocess,
            "run",
            return_value=self.fake_completed(stdout=json.dumps(payload)),
        ):
            internal = deliver_result.probe_identity()
        self.assertEqual(internal["delivery_mode"], "user")
        self.assertTrue(internal["_bot_ready"])

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            deliver_result, "probe_identity", return_value=internal
        ):
            public = deliver_result.execute_probe(
                "public-probe", temporary, str(Path(temporary) / "probe.log")
            )
        self.assertEqual(public["delivery_mode"], "user")
        self.assertTrue(public["ready"])
        self.assertNotIn("user_open_id", public)
        self.assertNotIn("user_name", public)
        self.assertNotIn("_bot_ready", public)

    def test_probe_falls_back_to_ready_bot_then_local_only(self):
        payload = auth_payload(["im:message"], bot_ready=True)
        with mock.patch.object(deliver_result.shutil, "which", return_value="fake-lark-cli"), mock.patch.object(
            deliver_result.subprocess,
            "run",
            return_value=self.fake_completed(stdout=json.dumps(payload)),
        ):
            self.assertEqual(deliver_result.probe_identity()["delivery_mode"], "bot")

        payload["identities"]["bot"]["available"] = False
        with mock.patch.object(deliver_result.shutil, "which", return_value="fake-lark-cli"), mock.patch.object(
            deliver_result.subprocess,
            "run",
            return_value=self.fake_completed(stdout=json.dumps(payload)),
        ):
            self.assertEqual(deliver_result.probe_identity()["delivery_mode"], "local_only")

        with mock.patch.object(deliver_result.shutil, "which", return_value=None):
            self.assertEqual(deliver_result.probe_identity()["feishu_status"], "cli_missing")

    def test_probe_does_not_let_root_verified_override_explicit_invalid_user(self):
        payload = auth_payload(["im:message", "im:message.send_as_user"], bot_ready=True)
        payload["identities"]["user"].update(
            {"verified": False, "status": "expired", "tokenStatus": "expired"}
        )
        with mock.patch.object(deliver_result.shutil, "which", return_value="fake-lark-cli"), mock.patch.object(
            deliver_result.subprocess,
            "run",
            return_value=self.fake_completed(stdout=json.dumps(payload)),
        ):
            self.assertEqual(deliver_result.probe_identity()["delivery_mode"], "bot")

        payload = auth_payload(["im:message", "im:message.send_as_user"], bot_ready=True)
        payload["identities"]["user"]["serverVerified"] = False
        with mock.patch.object(deliver_result.shutil, "which", return_value="fake-lark-cli"), mock.patch.object(
            deliver_result.subprocess,
            "run",
            return_value=self.fake_completed(stdout=json.dumps(payload)),
        ):
            self.assertEqual(deliver_result.probe_identity()["delivery_mode"], "bot")

    def test_log_path_priority_and_append_redaction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preferred = root / "preferred"
            home = root / "home"
            output = root / "output"
            preferred.mkdir()
            (home / "Desktop").mkdir(parents=True)
            output.mkdir()

            with mock.patch.object(deliver_result, "PREFERRED_DESKTOP", preferred), mock.patch.object(
                deliver_result.Path, "home", return_value=home
            ):
                self.assertEqual(
                    deliver_result.resolve_log_path(None, output),
                    preferred / deliver_result.LOG_FILENAME,
                )
                preferred.rmdir()
                self.assertEqual(
                    deliver_result.resolve_log_path(None, output),
                    home / "Desktop" / deliver_result.LOG_FILENAME,
                )
                (home / "Desktop").rmdir()
                self.assertEqual(
                    deliver_result.resolve_log_path(None, output),
                    home / ".codex" / "logs" / deliver_result.LOG_FILENAME,
                )

            explicit = root / "custom" / "activity.txt"
            self.assertEqual(deliver_result.resolve_log_path(str(explicit), output), explicit.resolve())
            ok, error = deliver_result.append_log(
                explicit,
                {
                    "run_id": "run-1",
                    "error_summary": "access_token=secret appSecret:another",
                },
            )
            self.assertTrue(ok)
            self.assertIsNone(error)
            text = explicit.read_text(encoding="utf-8")
            self.assertIn("run_id=run-1", text)
            self.assertNotIn("=secret", text)
            self.assertNotIn("another", text)

            deliver_result.append_log(
                explicit,
                {
                    "detail": (
                        '{"access_token":"json-secret","device_code":"code-secret",'
                        '"tenant_access_token":"tenant-secret",'
                        '"client_secret":"client-secret",'
                        '"open_id":"ou_private_identifier"} '
                        'chat_id=oc_private_identifier Authorization: Bearer bearer-secret-value'
                    )
                },
            )
            text = explicit.read_text(encoding="utf-8")
            self.assertNotIn("json-secret", text)
            self.assertNotIn("code-secret", text)
            self.assertNotIn("ou_private_identifier", text)
            self.assertNotIn("oc_private_identifier", text)
            self.assertNotIn("tenant-secret", text)
            self.assertNotIn("client-secret", text)
            self.assertNotIn("bearer-secret-value", text)

    def test_log_subcommand_appends_safe_lifecycle_event(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            output = root / "shot-01.png"
            source.write_bytes(b"source")
            output.write_bytes(b"output")
            log_file = root / "events.txt"
            result = deliver_result.execute_log(
                str(root),
                "run-log",
                "imagegen_retry",
                str(source),
                "shot-01",
                "retrying",
                "appSecret=must-not-leak",
                str(output),
                str(log_file),
            )
            self.assertTrue(result["ok"])
            text = log_file.read_text(encoding="utf-8")
            self.assertIn("event=imagegen_retry", text)
            self.assertIn("shot=shot-01", text)
            self.assertIn(str(source.resolve()), text)
            self.assertIn(str(output.resolve()), text)
            self.assertNotIn("must-not-leak", text)

    def test_deliver_saves_bom_files_and_sends_staged_relative_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = self.make_images(root)
            output = root / "result"
            log_file = root / "run.log"
            calls = []
            payload = auth_payload(["im:message", "im:message.send_as_user"])

            def fake_run(argv, **kwargs):
                calls.append((list(argv), dict(kwargs)))
                self.assertFalse(kwargs["shell"])
                if argv[1:5] == ["auth", "status", "--json", "--verify"]:
                    return self.fake_completed(stdout=json.dumps(payload))
                return self.fake_completed(stdout='{"message_id":"om_fake"}')

            with mock.patch.object(deliver_result.shutil, "which", return_value="fake-lark-cli"), mock.patch.object(
                deliver_result.subprocess, "run", side_effect=fake_run
            ):
                result = deliver_result.execute_deliver(
                    images,
                    "plain result text",
                    str(output),
                    "run 123",
                    True,
                    str(log_file),
                )

            self.assertEqual(result["delivery_status"], "dry_run")
            self.assertEqual(result["identity"], "user")
            self.assertEqual(result["images_sent"], 0)
            self.assertEqual(len(result["local_paths"]), 6)
            self.assertTrue(all(Path(path).is_file() for path in result["local_paths"]))
            expected_names = [
                "商品视频-01-hook.png",
                "商品视频-02-hero.png",
                "商品视频-03-use.png",
                "商品视频-04-detail.png",
                "商品视频-05-ending.png",
            ]
            self.assertEqual([Path(path).name for path in result["local_paths"][:5]], expected_names)
            result_txt = output / "商品视频-视频提示词.txt"
            self.assertTrue(result_txt.read_bytes().startswith(b"\xef\xbb\xbf"))
            result_text = result_txt.read_text(encoding="utf-8-sig")
            self.assertTrue(result_text.startswith("plain result text\n"))
            self.assertIn("飞书投递：dry_run/user — 仅预演，未真实发送", result_text)

            send_calls = calls[1:]
            self.assertEqual(len(send_calls), 6)
            keys = []
            for index, (argv, kwargs) in enumerate(send_calls[:5], start=1):
                self.assertEqual(argv[1:3], ["im", "+messages-send"])
                self.assertEqual(argv[argv.index("--as") + 1], "user")
                self.assertEqual(argv[argv.index("--user-id") + 1], "test-dynamic-self-id")
                image_arg = argv[argv.index("--image") + 1]
                self.assertEqual(image_arg, "./{}".format(expected_names[index - 1]))
                self.assertFalse(Path(image_arg).is_absolute())
                self.assertIn("--dry-run", argv)
                self.assertNotEqual(Path(kwargs["cwd"]), output)
                keys.append(argv[argv.index("--idempotency-key") + 1])
            text_argv = send_calls[-1][0]
            self.assertEqual(text_argv[text_argv.index("--text") + 1], "plain result text")
            keys.append(text_argv[text_argv.index("--idempotency-key") + 1])
            self.assertEqual(len(keys), len(set(keys)))
            self.assertNotEqual(
                deliver_result._idempotency_key("same-run", "image", 1, "content-a"),
                deliver_result._idempotency_key("same-run", "image", 1, "content-b"),
            )
            self.assertIn("local_saved=True", log_file.read_text(encoding="utf-8"))

    def test_prefix_sanitizing_conflict_suffix_and_existing_target_safety(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = self.make_images(root)
            output = root / "result"
            output.mkdir()
            occupied = output / "Bad_Name-01-hook.png"
            occupied.write_bytes(b"do-not-overwrite")
            probe = {"delivery_mode": "local_only", "error": "offline"}
            with mock.patch.object(deliver_result, "probe_identity", return_value=probe):
                result = deliver_result.execute_deliver(
                    images,
                    "text",
                    str(output),
                    "conflict-run",
                    False,
                    str(root / "log.txt"),
                    "Bad<Name",
                )
            self.assertRegex(result["output_prefix"], r"^Bad_Name-\d{8}-\d{6}(?:-\d{2})?$")
            self.assertEqual(occupied.read_bytes(), b"do-not-overwrite")
            self.assertTrue(all(Path(path).name.startswith(result["output_prefix"]) for path in result["local_paths"]))

    def test_source_already_at_final_target_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "result"
            output.mkdir()
            images = []
            for index, role in enumerate(deliver_result.SHOT_ROLES, start=1):
                path = output / "Ready-{:02d}-{}.png".format(index, role)
                path.write_bytes("original-{}".format(index).encode("ascii"))
                images.append(str(path))
            before = [Path(path).read_bytes() for path in images]
            probe = {"delivery_mode": "local_only", "error": "offline"}
            with mock.patch.object(deliver_result, "probe_identity", return_value=probe):
                result = deliver_result.execute_deliver(
                    images,
                    "text",
                    str(output),
                    "same-file-run",
                    False,
                    str(root / "log.txt"),
                    "Ready",
                )
            self.assertEqual(result["output_prefix"], "Ready")
            self.assertEqual([Path(path).read_bytes() for path in images], before)

    def test_missing_role_still_detects_whole_batch_prefix_conflict(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "result"
            output.mkdir()
            source = root / "hook.png"
            source.write_bytes(b"hook")
            (output / "Batch-03-use.png").write_bytes(b"older-run")
            probe = {"delivery_mode": "local_only", "error": "offline"}
            with mock.patch.object(deliver_result, "probe_identity", return_value=probe):
                result = deliver_result.execute_deliver(
                    ["01-hook={}".format(source)],
                    "text",
                    str(output),
                    "missing-conflict-run",
                    False,
                    str(root / "log.txt"),
                    "Batch",
                )
            self.assertRegex(result["output_prefix"], r"^Batch-\d{8}-\d{6}(?:-\d{2})?$")
            self.assertEqual((output / "Batch-03-use.png").read_bytes(), b"older-run")

    def test_zero_images_still_saves_and_sends_plain_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "result"
            probe = {
                "delivery_mode": "bot",
                "_cli_path": "fake-lark-cli",
                "user_open_id": "test-dynamic-self-id",
                "error": None,
            }
            with mock.patch.object(deliver_result, "probe_identity", return_value=probe), mock.patch.object(
                deliver_result.subprocess, "run", return_value=self.fake_completed()
            ) as run:
                result = deliver_result.execute_deliver(
                    [], "text only", str(output), "zero-run", False, str(root / "log.txt"), "Zero"
                )
            self.assertEqual(result["delivery_status"], "sent")
            self.assertEqual(result["images_sent"], 0)
            self.assertEqual(len(result["local_paths"]), 1)
            self.assertEqual(Path(result["local_paths"][0]).name, "Zero-视频提示词.txt")
            self.assertEqual(run.call_count, 1)
            argv = run.call_args.args[0]
            self.assertIn("--text", argv)

    def test_explicit_roles_keep_middle_gap_without_renumbering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source1 = root / "one.png"
            source4 = root / "four.png"
            source5 = root / "five.png"
            for path in (source1, source4, source5):
                path.write_bytes(path.name.encode("ascii"))
            specs = [
                "01-hook={}".format(source1),
                "04-detail={}".format(source4),
                "05-ending={}".format(source5),
            ]
            probe = {"delivery_mode": "local_only", "error": "cli_missing"}
            with mock.patch.object(deliver_result, "probe_identity", return_value=probe):
                result = deliver_result.execute_deliver(
                    specs,
                    "text",
                    str(root / "result"),
                    "gap-run",
                    False,
                    str(root / "log.txt"),
                    "Gap",
                )
            self.assertEqual(
                [Path(path).name for path in result["local_paths"][:-1]],
                ["Gap-01-hook.png", "Gap-04-detail.png", "Gap-05-ending.png"],
            )
            text = Path(result["local_paths"][-1]).read_text(encoding="utf-8-sig")
            self.assertIn("飞书投递：local_only — cli_missing", text)

            non_contiguous = root / "Ready-04-detail.png"
            non_contiguous.write_bytes(b"detail")
            with self.assertRaises(deliver_result.DeliveryError):
                deliver_result._parse_image_specs([str(non_contiguous)])

    def test_user_failure_switches_to_ready_bot_from_current_item(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = self.make_images(root)
            probe = {
                "delivery_mode": "user",
                "_cli_path": "fake-lark-cli",
                "_bot_ready": True,
                "user_open_id": "test-dynamic-self-id",
                "error": None,
            }
            responses = [
                self.fake_completed(),
                self.fake_completed(1, stderr="permission denied: missing scope"),
                self.fake_completed(),
                self.fake_completed(),
                self.fake_completed(),
                self.fake_completed(),
                self.fake_completed(),
            ]
            with mock.patch.object(deliver_result, "probe_identity", return_value=probe), mock.patch.object(
                deliver_result.subprocess, "run", side_effect=responses
            ) as run:
                result = deliver_result.execute_deliver(
                    images,
                    "text",
                    str(root / "result"),
                    "mixed-run",
                    False,
                    str(root / "log.txt"),
                    "Mixed",
                )
            self.assertEqual(run.call_count, 7)
            identities = [
                call.args[0][call.args[0].index("--as") + 1] for call in run.call_args_list
            ]
            self.assertEqual(identities, ["user", "user", "bot", "bot", "bot", "bot", "bot"])
            second_user = run.call_args_list[1].args[0]
            second_bot = run.call_args_list[2].args[0]
            self.assertEqual(
                second_user[second_user.index("--idempotency-key") + 1],
                second_bot[second_bot.index("--idempotency-key") + 1],
            )
            self.assertEqual(result["delivery_status"], "sent")
            self.assertEqual(result["identity"], "mixed")
            self.assertTrue(result["delivery_summary"].startswith("mixed — "))
            text = Path(result["local_paths"][-1]).read_text(encoding="utf-8-sig")
            self.assertIn("飞书投递：mixed — ", text)

    def test_transient_failure_retries_once_permission_failure_does_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = self.make_images(root)
            output = root / "result"
            log_file = root / "run.log"
            probe = {
                "delivery_mode": "bot",
                "_cli_path": "fake-lark-cli",
                "user_open_id": "test-dynamic-self-id",
                "error": None,
            }
            responses = [
                self.fake_completed(1, stderr="temporary network timeout"),
                self.fake_completed(),
            ] + [self.fake_completed()] * 5

            with mock.patch.object(deliver_result, "probe_identity", return_value=probe), mock.patch.object(
                deliver_result.subprocess, "run", side_effect=responses
            ) as run:
                result = deliver_result.execute_deliver(
                    images, "text", str(output), "retry-run", False, str(log_file)
                )
            self.assertEqual(result["delivery_status"], "sent")
            self.assertEqual(run.call_count, 7)

            output2 = root / "result2"
            with mock.patch.object(deliver_result, "probe_identity", return_value=probe), mock.patch.object(
                deliver_result.subprocess,
                "run",
                return_value=self.fake_completed(1, stderr="permission denied: missing scope"),
            ) as run:
                result = deliver_result.execute_deliver(
                    images, "text", str(output2), "permission-run", False, str(log_file)
                )
            self.assertEqual(result["delivery_status"], "failed")
            self.assertEqual(run.call_count, 1)
            self.assertEqual(len(result["local_paths"]), 6)
            self.assertTrue(all(Path(path).is_file() for path in result["local_paths"]))
            self.assertIn("auth_or_permission_error", result["error"])

    def test_main_stdout_is_single_json_object(self):
        with tempfile.TemporaryDirectory() as temporary:
            log_file = Path(temporary) / "probe.log"
            probe = {
                "ok": True,
                "delivery_mode": "local_only",
                "cli_available": False,
                "feishu_status": "cli_missing",
                "user_open_id": None,
                "user_name": None,
                "error": "cli_missing",
                "_cli_path": None,
            }
            stdout = io.StringIO()
            with mock.patch.object(deliver_result, "probe_identity", return_value=probe), mock.patch.object(
                sys, "stdout", stdout
            ):
                exit_code = deliver_result.main(
                    ["probe", "--run-id", "test", "--log-file", str(log_file)]
                )
            self.assertEqual(exit_code, 0)
            lines = stdout.getvalue().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["delivery_mode"], "local_only")

    def test_main_logs_too_many_images_and_keeps_json_stdout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = []
            for index in range(6):
                image = root / "image-{}.png".format(index)
                image.write_bytes(b"image")
                images.append(str(image))
            stdout = io.StringIO()
            stdin = io.StringIO("text")
            log_file = root / "failure.log"
            argv = ["deliver"]
            for image in images:
                argv.extend(["--image", image])
            argv.extend(
                [
                    "--result-text-stdin",
                    "--output-dir",
                    str(root / "result"),
                    "--run-id",
                    "bad-count",
                    "--log-file",
                    str(log_file),
                ]
            )
            with mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stdin", stdin):
                exit_code = deliver_result.main(argv)
            self.assertEqual(exit_code, 2)
            lines = stdout.getvalue().splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["delivery_status"], "failed")
            self.assertEqual(payload["local_paths"], [])
            self.assertEqual(payload["delivery_status"], "failed")
            self.assertEqual(payload["local_paths"], [])
            self.assertIn("at_most_5_images_allowed", payload["error"])
            self.assertIn("error_summary=at_most_5_images_allowed", log_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
