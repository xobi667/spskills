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


FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n"
    + (13).to_bytes(4, "big")
    + b"IHDR"
    + (1).to_bytes(4, "big")
    + (1).to_bytes(4, "big")
    + bytes((8, 6, 0, 0, 0))
)


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
        for index in range(1, 7):
            path = Path(root) / "source-{}.png".format(index)
            path.write_bytes(FAKE_PNG)
            image_paths.append(str(path))
        return image_paths

    def director_text(self, label="prompt", failure=None):
        blocks = []
        for index in range(1, 6):
            blocks.append(
                "{0:02d}｜镜头{0:02d}\n首尾帧：{0:02d}.png → {1:02d}.png\n"
                "提示词：{2}-{0:02d}".format(index, index + 1, label)
            )
        header = "项目：测试商品\n规格：9:16｜5 段｜每段 4–6 秒"
        if failure:
            header += "\n生图：失败（{}）".format(failure)
        return header + "\n\n" + "\n\n".join(blocks)

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
            director_text = self.director_text("plain")
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
                    director_text,
                    str(output),
                    "run 123",
                    True,
                    str(log_file),
                )

            self.assertEqual(result["delivery_status"], "dry_run")
            self.assertEqual(result["identity"], "user")
            self.assertEqual(result["images_sent"], 0)
            self.assertEqual(len(result["local_paths"]), 7)
            self.assertTrue(all(Path(path).is_file() for path in result["local_paths"]))
            expected_names = [
                "01.png",
                "02.png",
                "03.png",
                "04.png",
                "05.png",
                "06.png",
            ]
            self.assertEqual([Path(path).name for path in result["local_paths"][:6]], expected_names)
            result_txt = output / "导演台.txt"
            self.assertTrue(result_txt.read_bytes().startswith(b"\xef\xbb\xbf"))
            result_text = result_txt.read_text(encoding="utf-8-sig")
            self.assertEqual(result_text, director_text + "\n")
            self.assertNotIn("飞书投递", result_text)

            send_calls = calls[1:]
            self.assertEqual(len(send_calls), 7)
            keys = []
            for index, (argv, kwargs) in enumerate(send_calls[:6], start=1):
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
            self.assertEqual(text_argv[text_argv.index("--text") + 1], director_text)
            keys.append(text_argv[text_argv.index("--idempotency-key") + 1])
            self.assertEqual(len(keys), len(set(keys)))
            self.assertNotEqual(
                deliver_result._idempotency_key("same-run", "image", 1, "content-a"),
                deliver_result._idempotency_key("same-run", "image", 1, "content-b"),
            )
            self.assertIn("local_saved=True", log_file.read_text(encoding="utf-8"))

    def test_init_file_uses_parent_sanitizes_name_and_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            source.write_bytes(b"source")
            log_file = root / "init.log"
            with mock.patch.object(
                deliver_result, "_project_timestamp", return_value="20260714-120000"
            ):
                result = deliver_result.execute_init(
                    str(source), None, "Bad<Name", "init-file", str(log_file)
                )
            project = Path(result["project_dir"])
            self.assertEqual(project.parent, root.resolve())
            self.assertEqual(project.name, "Bad_Name_导演台_20260714-120000")
            self.assertTrue(project.is_dir())
            self.assertEqual(result["output_dir"], str(project))
            self.assertEqual(
                [Path(path).name for path in result["image_targets"]],
                ["01.png", "02.png", "03.png", "04.png", "05.png", "06.png"],
            )
            self.assertEqual(Path(result["text_target"]).name, "导演台.txt")
            self.assertIn("command=init", log_file.read_text(encoding="utf-8"))

    def test_init_directory_and_base_override_use_collision_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_dir = root / "输入商品"
            source_dir.mkdir()
            override = root / "exports"
            with mock.patch.object(
                deliver_result, "_project_timestamp", return_value="20260714-120000"
            ):
                first = deliver_result.execute_init(
                    str(source_dir), None, None, "dir-1", str(root / "init.log")
                )
                second = deliver_result.execute_init(
                    str(source_dir), None, None, "dir-2", str(root / "init.log")
                )
                third = deliver_result.execute_init(
                    str(source_dir),
                    str(override),
                    None,
                    "dir-3",
                    str(root / "init.log"),
                )
            self.assertEqual(
                Path(first["project_dir"]).name,
                "输入商品_导演台_20260714-120000",
            )
            self.assertEqual(
                Path(second["project_dir"]).name,
                "输入商品_导演台_20260714-120000-02",
            )
            self.assertEqual(Path(first["project_dir"]).parent, source_dir.resolve())
            self.assertEqual(Path(third["project_dir"]).parent, override.resolve())

    def test_main_init_subcommand_returns_one_json_object(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "product.png"
            source.write_bytes(b"source")
            stdout = io.StringIO()
            with mock.patch.object(
                deliver_result, "_project_timestamp", return_value="20260714-130000"
            ), mock.patch.object(sys, "stdout", stdout):
                exit_code = deliver_result.main(
                    [
                        "init",
                        "--source",
                        str(source),
                        "--run-id",
                        "cli-init",
                        "--log-file",
                        str(root / "init.log"),
                    ]
                )
            self.assertEqual(exit_code, 0)
            lines = stdout.getvalue().splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["command"], "init")
            self.assertEqual(len(payload["image_targets"]), 6)
            self.assertTrue(Path(payload["project_dir"]).is_dir())

    def test_source_already_at_final_target_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "result"
            output.mkdir()
            images = []
            for index in range(1, 7):
                path = output / "{:02d}.png".format(index)
                path.write_bytes(FAKE_PNG)
                images.append(str(path))
            before = [Path(path).read_bytes() for path in images]
            probe = {"delivery_mode": "local_only", "error": "offline"}
            with mock.patch.object(deliver_result, "probe_identity", return_value=probe):
                result = deliver_result.execute_deliver(
                    images,
                    self.director_text("same-file"),
                    str(output),
                    "same-file-run",
                    False,
                    str(root / "log.txt"),
                )
            self.assertEqual(Path(result["project_dir"]), output.resolve())
            self.assertEqual([Path(path).read_bytes() for path in images], before)

    def test_existing_numbered_target_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "result"
            output.mkdir()
            source = root / "new.png"
            source.write_bytes(FAKE_PNG)
            occupied = output / "01.png"
            occupied.write_bytes(b"older-run")
            with self.assertRaises(deliver_result.DeliveryError):
                deliver_result.execute_deliver(
                    ["01={}".format(source)],
                    self.director_text("conflict"),
                    str(output),
                    "conflict-run",
                    False,
                    str(root / "log.txt"),
                )
            self.assertEqual(occupied.read_bytes(), b"older-run")

    def test_non_png_result_is_rejected_instead_of_renamed(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "renamed-jpeg.png"
            source.write_bytes(b"jpeg-content")
            with self.assertRaisesRegex(
                deliver_result.DeliveryError, "invalid_png_content:01"
            ):
                deliver_result._parse_image_specs(["01={}".format(source)])

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
                    [],
                    self.director_text("zero"),
                    str(output),
                    "zero-run",
                    False,
                    str(root / "log.txt"),
                )
            self.assertEqual(result["delivery_status"], "sent")
            self.assertEqual(result["images_sent"], 0)
            self.assertEqual(len(result["local_paths"]), 1)
            self.assertEqual(Path(result["local_paths"][0]).name, "导演台.txt")
            self.assertEqual(run.call_count, 1)
            argv = run.call_args.args[0]
            self.assertIn("--text", argv)

    def test_explicit_numbers_keep_middle_gap_without_renumbering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source1 = root / "one.png"
            source4 = root / "four.png"
            source6 = root / "six.png"
            for path in (source1, source4, source6):
                path.write_bytes(FAKE_PNG)
            specs = [
                "01={}".format(source1),
                "04={}".format(source4),
                "06={}".format(source6),
            ]
            probe = {"delivery_mode": "local_only", "error": "cli_missing"}
            with mock.patch.object(deliver_result, "probe_identity", return_value=probe):
                result = deliver_result.execute_deliver(
                    specs,
                    self.director_text("gap"),
                    str(root / "result"),
                    "gap-run",
                    False,
                    str(root / "log.txt"),
                )
            self.assertEqual(
                [Path(path).name for path in result["local_paths"][:-1]],
                ["01.png", "04.png", "06.png"],
            )
            text = Path(result["local_paths"][-1]).read_text(encoding="utf-8-sig")
            self.assertEqual(text, self.director_text("gap") + "\n")
            self.assertNotIn("飞书投递", text)

            non_contiguous = root / "04.png"
            non_contiguous.write_bytes(b"detail")
            with self.assertRaises(deliver_result.DeliveryError):
                deliver_result._parse_image_specs([str(non_contiguous)])

    def test_director_text_requires_five_prompts_and_six_frame_chain(self):
        valid = self.director_text("chain")
        deliver_result._validate_result_text(valid)
        deliver_result._validate_result_text(self.director_text("chain", "工具不可用"))

        wrong_mapping = valid.replace("首尾帧：03.png → 04.png", "首尾帧：03.png → 05.png")
        with self.assertRaisesRegex(deliver_result.DeliveryError, "invalid_frame_mapping:03"):
            deliver_result._validate_result_text(wrong_mapping)

        duplicate_prompt = valid.replace(
            "提示词：chain-02", "提示词：chain-02\n提示词：duplicate"
        )
        with self.assertRaisesRegex(deliver_result.DeliveryError, "segment_requires_one_prompt:02"):
            deliver_result._validate_result_text(duplicate_prompt)

        with_sixth_segment = valid + "\n\n06｜不允许\n提示词：extra"
        with self.assertRaisesRegex(
            deliver_result.DeliveryError, "director_text_contains_extra_content"
        ):
            deliver_result._validate_result_text(with_sixth_segment)

        extra_analysis = valid.replace(
            "规格：9:16｜5 段｜每段 4–6 秒",
            "规格：9:16｜5 段｜每段 4–6 秒\n商品真值摘要：不应出现在导演台",
        )
        with self.assertRaisesRegex(
            deliver_result.DeliveryError, "director_text_requires_segments_01_to_05"
        ):
            deliver_result._validate_result_text(extra_analysis)

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
                self.fake_completed(),
            ]
            with mock.patch.object(deliver_result, "probe_identity", return_value=probe), mock.patch.object(
                deliver_result.subprocess, "run", side_effect=responses
            ) as run:
                result = deliver_result.execute_deliver(
                    images,
                    self.director_text("mixed"),
                    str(root / "result"),
                    "mixed-run",
                    False,
                    str(root / "log.txt"),
                )
            self.assertEqual(run.call_count, 8)
            identities = [
                call.args[0][call.args[0].index("--as") + 1] for call in run.call_args_list
            ]
            self.assertEqual(
                identities,
                ["user", "user", "bot", "bot", "bot", "bot", "bot", "bot"],
            )
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
            self.assertEqual(text, self.director_text("mixed") + "\n")
            self.assertNotIn("飞书投递", text)

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
            ] + [self.fake_completed()] * 6

            with mock.patch.object(deliver_result, "probe_identity", return_value=probe), mock.patch.object(
                deliver_result.subprocess, "run", side_effect=responses
            ) as run:
                result = deliver_result.execute_deliver(
                    images,
                    self.director_text("retry"),
                    str(output),
                    "retry-run",
                    False,
                    str(log_file),
                )
            self.assertEqual(result["delivery_status"], "sent")
            self.assertEqual(run.call_count, 8)

            output2 = root / "result2"
            with mock.patch.object(deliver_result, "probe_identity", return_value=probe), mock.patch.object(
                deliver_result.subprocess,
                "run",
                return_value=self.fake_completed(1, stderr="permission denied: missing scope"),
            ) as run:
                result = deliver_result.execute_deliver(
                    images,
                    self.director_text("permission"),
                    str(output2),
                    "permission-run",
                    False,
                    str(log_file),
                )
            self.assertEqual(result["delivery_status"], "failed")
            self.assertEqual(run.call_count, 1)
            self.assertEqual(len(result["local_paths"]), 7)
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
            for index in range(7):
                image = root / "image-{}.png".format(index)
                image.write_bytes(b"image")
                images.append(str(image))
            stdout = io.StringIO()
            stdin = io.StringIO(self.director_text("too-many"))
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
            self.assertIn("at_most_6_images_allowed", payload["error"])
            self.assertIn("error_summary=at_most_6_images_allowed", log_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
