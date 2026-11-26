"""Tests for chatgpt_share_md converter and web server."""

import http.client
import io
import json
import tempfile
import threading
import urllib.error
import urllib.request
import unittest
from email.message import Message
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from chatgpt_share_md import converter

from chatgpt_share_md.converter import (
    ConvertError,
    convert_html_to_markdown,
    normalize_share_url,
    slugify,
)
from chatgpt_share_md.web import WebHandler


# Minimal HTML fixture mimicking the React Router stream payload
SAMPLE_REACT_ROUTER_HTML = r"""<!DOCTYPE html>
<html>
<head><title>ChatGPT</title></head>
<body>
<script>
window.__reactRouterContext = {
  streamController: {
    enqueue: function(x) {}
  }
};
window.__reactRouterContext.streamController.enqueue("[{\"loaderData\": 1}, {\"routes/share\": 2}, {\"serverResponse\": 3}, {\"data\": 4}, {\"title\": \"My Test Chat\", \"conversation_id\": \"12345\", \"create_time\": 14, \"update_time\": 15, \"linear_conversation\": 5}, [6, 7], {\"message\": 8}, {\"message\": 9}, {\"author\": 10, \"content\": 11, \"create_time\": 14}, {\"author\": 12, \"content\": 13, \"create_time\": 15}, {\"role\": \"user\"}, {\"parts\": [\"Hello, tell me a joke.\"]}, {\"role\": \"assistant\"}, {\"parts\": [\"Why did the chicken cross the road?\"]}, 1700000000, 1700000010]");
</script>
</body>
</html>
"""

# Minimal Next.js legacy payload
SAMPLE_NEXT_DATA_HTML = """<!DOCTYPE html>
<html>
<head><title>ChatGPT</title></head>
<body>
<script id="__NEXT_DATA__" type="application/json">
{
  "props": {
    "pageProps": {
      "serverResponse": {
        "data": {
          "title": "Legacy Share",
          "conversation_id": "legacy-999",
          "linear_conversation": [
            {
              "message": {
                "author": {"role": "user"},
                "content": {"parts": ["Legacy question"]}
              }
            },
            {
              "message": {
                "author": {"role": "assistant"},
                "content": {"parts": ["Legacy answer"]}
              }
            }
          ]
        }
      }
    }
  }
}
</script>
</body>
</html>
"""


class TestConverter(unittest.TestCase):
    def test_normalize_share_url(self):
        url = "https://chatgpt.com/share/6a793ced-ed18-83ea-b2e6-66d3cf2917fb"
        self.assertEqual(normalize_share_url(url), url)

        www_url = "https://www.chatgpt.com/share/abc-123"
        self.assertEqual(normalize_share_url(www_url), "https://chatgpt.com/share/abc-123")

        with self.assertRaises(ConvertError):
            normalize_share_url("https://example.com/share/123")

        with self.assertRaises(ConvertError):
            normalize_share_url("https://chatgpt.com/c/private-chat")

    def test_slugify(self):
        self.assertEqual(slugify("Hello World!"), "hello-world")
        self.assertEqual(slugify("Comment ça va ?"), "comment-ça-va")

    def test_convert_react_router_html(self):
        markdown, metadata = convert_html_to_markdown(
            SAMPLE_REACT_ROUTER_HTML,
            source="https://chatgpt.com/share/mock-id",
        )
        self.assertIn("# My Test Chat", markdown)
        self.assertIn("## 1. User", markdown)
        self.assertIn("Hello, tell me a joke.", markdown)
        self.assertIn("## 2. Assistant", markdown)
        self.assertIn("Why did the chicken cross the road?", markdown)
        self.assertEqual(len(metadata["messages"]), 2)
        self.assertEqual(metadata["title"], "My Test Chat")

    def test_convert_legacy_html(self):
        markdown, metadata = convert_html_to_markdown(SAMPLE_NEXT_DATA_HTML)
        self.assertIn("# Legacy Share", markdown)
        self.assertIn("Legacy question", markdown)
        self.assertIn("Legacy answer", markdown)
        self.assertEqual(len(metadata["messages"]), 2)


class TestJsonAcquisition(unittest.TestCase):
    URL = "https://chatgpt.com/share/synthetic-id"

    def conversation(self):
        return {
            "title": "Synthetic chat",
            "linear_conversation": [
                {"message": {"author": {"role": role},
                             "content": {"parts": [text]}, "create_time": 1700000000}}
                for role, text in (("user", "Question"), ("assistant", "Answer"))
            ],
        }

    def response(self, body, content_type="application/json"):
        response = io.BytesIO(body)
        response.headers = Message()
        response.headers["Content-Type"] = content_type + "; charset=utf-8"
        return response

    def html(self, conversation):
        payload = {"props": {"pageProps": {"serverResponse": {"data": conversation}}}}
        return '<script id="__NEXT_DATA__">' + json.dumps(payload) + '</script>'

    def interrupted_response(self, error):
        response = self.response(b"")
        response.read = Mock(side_effect=error)
        return response

    def test_json_first_uses_shared_renderer_and_metadata(self):
        conversation = self.conversation()
        expected = convert_html_to_markdown(self.html(conversation), self.URL)
        with patch.object(converter.urllib.request, "urlopen", return_value=self.response(
            json.dumps(conversation).encode()
        )) as opened, patch.object(converter, "fetch_html") as html_fetch, patch.object(
            converter, "build_markdown", wraps=converter.build_markdown
        ) as renderer, patch.object(converter, "convert_html_to_markdown") as html_parser:
            actual = converter.convert_source(self.URL, timeout=7)
        self.assertEqual(actual, expected)
        renderer.assert_called_once()
        html_fetch.assert_not_called()
        html_parser.assert_not_called()
        opened.assert_called_once()
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://chatgpt.com/backend-api/share/synthetic-id")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(opened.call_args.kwargs, {"timeout": 7})
        metadata = actual[1]
        for key in ("conversation_id", "created_at", "updated_at"):
            self.assertIsNone(metadata[key])
        self.assertEqual(metadata["messages"][0]["created_at"], 1700000000)

    def test_direct_schema_requires_no_optional_metadata(self):
        conversation = self.conversation()
        del conversation["title"]
        conversation["linear_conversation"].insert(0, {"message": None})
        self.assertIs(converter.validate_direct_conversation(conversation), conversation)
        with patch.object(converter.urllib.request, "urlopen", return_value=self.response(
            json.dumps(conversation).encode()
        )):
            markdown, metadata = converter.convert_source(self.URL)
        self.assertIn("# ChatGPT conversation", markdown)
        self.assertNotIn("Conversation ID:", markdown)
        self.assertIsNone(metadata["conversation_id"])
        self.assertNotIn("conversation_id", conversation)

    def test_expected_json_failures_fall_back_to_html(self):
        failures = [
            urllib.error.HTTPError(self.URL, code, "private diagnostic", {}, None)
            for code in (403, 404)
        ] + [TimeoutError("private diagnostic"), urllib.error.URLError("private diagnostic")]
        failures.extend([
            self.interrupted_response(http.client.IncompleteRead(b"secret")),
            self.interrupted_response(ConnectionResetError("secret")),
        ])
        bodies = [b"<html>Not JSON</html>", b'{"broken":', b'\xff', b'[]', b'{}',
                  b'{"data": {"linear_conversation": []}}',
                  b'{"linear_conversation": {}}',
                  b'{"linear_conversation": []}',
                  b'{"linear_conversation": [1]}',
                  b'{"linear_conversation": [{"message": "bad"}]}',
                  b'{"linear_conversation": [], "title": 123}',
                  b'{"linear_conversation": [{"message": {"author": "bad"}}]}',
                  b'{"linear_conversation": [{"message": {"author": {"role": []}}}]}',
                  b'{"linear_conversation": [{"message": {"content": "bad"}}]}',
                  b'{"linear_conversation": [{"message": {"content": {"parts": "bad"}}}]}']
        for index, failure in enumerate(failures + bodies):
            with self.subTest(case=index):
                first = self.response(failure) if isinstance(failure, bytes) else failure
                with patch.object(converter.urllib.request, "urlopen", side_effect=[
                    first, self.response(SAMPLE_REACT_ROUTER_HTML.encode(), "text/html")
                ]) as opened:
                    result = converter.convert_source(self.URL, timeout=9)
                self.assertEqual(result, convert_html_to_markdown(SAMPLE_REACT_ROUTER_HTML, self.URL))
                self.assertEqual(opened.call_count, 2)
                self.assertEqual(opened.call_args_list[1].args[0].full_url, self.URL)
                self.assertEqual(opened.call_args_list[1].kwargs, {"timeout": 9})

    def test_non_json_response_falls_back_to_legacy_html(self):
        with patch.object(converter.urllib.request, "urlopen", side_effect=[
            self.response(b"<html>Unavailable</html>", "text/html"),
            self.response(SAMPLE_NEXT_DATA_HTML.encode(), "text/html"),
        ]):
            self.assertEqual(
                converter.convert_source(self.URL),
                convert_html_to_markdown(SAMPLE_NEXT_DATA_HTML, self.URL),
            )

    def test_both_fail_with_sanitized_reasons(self):
        for second, reason in ((TimeoutError("secret"), "Timed out"),
                               (urllib.error.URLError("secret"), "Network error"),
                               (self.interrupted_response(http.client.IncompleteRead(b"secret")), "Network error"),
                               (self.interrupted_response(ConnectionResetError("secret")), "Network error"),
                               (urllib.error.HTTPError(self.URL, 404, "secret", {}, None), "HTTP 404"),
                               (b"<html>secret</html>", "No ChatGPT conversation payload")):
            with self.subTest(reason=reason):
                second = self.response(second) if isinstance(second, bytes) else second
                with patch.object(converter.urllib.request, "urlopen", side_effect=[
                    urllib.error.HTTPError(self.URL, 403, "secret", {}, None), second
                ]), self.assertRaises(ConvertError) as caught:
                    converter.convert_source(self.URL)
                message = str(caught.exception)
                for expected in ("Both strategies failed", "JSON:", "HTTP 403", "HTML:", reason):
                    self.assertIn(expected, message)
                self.assertNotIn("secret", message)
                self.assertTrue(caught.exception.__suppress_context__)

    def test_programming_errors_do_not_trigger_fallback(self):
        for error in (TypeError("bug"), ValueError("bug"), RuntimeError("bug")):
            with self.subTest(error=type(error).__name__), patch.object(
                converter.urllib.request, "urlopen", side_effect=error
            ), patch.object(converter, "fetch_html") as html_fetch:
                with self.assertRaises(type(error)):
                    converter.convert_source(self.URL)
                html_fetch.assert_not_called()
        with patch.object(converter, "fetch_share_json", return_value=self.conversation()), \
                patch.object(converter, "build_markdown", side_effect=TypeError("bug")), \
                patch.object(converter, "fetch_html") as html_fetch:
            with self.assertRaises(TypeError):
                converter.convert_source(self.URL)
            html_fetch.assert_not_called()
        with patch.object(converter, "fetch_share_json", side_effect=ConvertError("unavailable")), \
                patch.object(converter, "fetch_html", return_value=SAMPLE_NEXT_DATA_HTML), \
                patch.object(converter, "convert_html_to_markdown", side_effect=TypeError("bug")):
            with self.assertRaises(TypeError):
                converter.convert_source(self.URL)

    def test_only_explicit_boolean_hidden_flag_filters_messages(self):
        for flag in (False, None, 0, 1, "true"):
            with self.subTest(flag=flag):
                conversation = self.conversation()
                for node in conversation["linear_conversation"]:
                    node["message"]["metadata"] = {"is_visually_hidden_from_conversation": flag}
                    node["message"]["channel"] = "analysis"
                messages = converter.extract_messages(
                    conversation, include_tools=False, include_system=False
                )
                self.assertEqual(len(messages), 2)

    def test_visibility_and_role_flags_for_both_inputs(self):
        conversation = self.conversation()
        conversation["linear_conversation"] = [
            {"message": {"author": {"role": role}, "content": {"parts": [
                ("hidden " if hidden else "visible ") + role]},
                "metadata": {"is_visually_hidden_from_conversation": hidden},
                "channel": "unfamiliar"}}
            for hidden in (False, True) for role in ("system", "user", "assistant", "tool")
        ]
        for include_system in (False, True):
            for include_tools in (False, True):
                with self.subTest(system=include_system, tools=include_tools):
                    options = dict(include_system=include_system, include_tools=include_tools)
                    html_result = convert_html_to_markdown(self.html(conversation), self.URL, **options)
                    with patch.object(converter.urllib.request, "urlopen", return_value=self.response(
                        json.dumps(conversation).encode()
                    )):
                        direct_result = converter.convert_source(self.URL, **options)
                    self.assertEqual(direct_result, html_result)
                    markdown, metadata = direct_result
                    self.assertNotIn("hidden", markdown)
                    self.assertNotIn("hidden", json.dumps(metadata))
                    roles = [m["role"] for m in metadata["messages"]]
                    self.assertEqual(roles, (["system"] if include_system else []) +
                                     ["user", "assistant"] + (["tool"] if include_tools else []))

    def test_saved_html_is_offline_and_read_source_stays_html(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "saved.html"
            path.write_text(SAMPLE_NEXT_DATA_HTML, encoding="utf-8")
            with patch.object(converter.urllib.request, "urlopen") as opened:
                self.assertEqual(converter.read_source(str(path), 30), (SAMPLE_NEXT_DATA_HTML, None))
                result = converter.convert_source(str(path))
                opened.assert_not_called()
            self.assertEqual(result, convert_html_to_markdown(SAMPLE_NEXT_DATA_HTML, str(path)))
        with patch.object(converter.urllib.request, "urlopen", return_value=self.response(
            SAMPLE_NEXT_DATA_HTML.encode()
        )) as opened:
            self.assertEqual(converter.read_source(self.URL, 30), (SAMPLE_NEXT_DATA_HTML, self.URL))
            self.assertEqual(opened.call_args.args[0].full_url, self.URL)

    def test_supported_domains_use_fixed_backend(self):
        for host in ("chatgpt.com", "www.chatgpt.com", "chat.openai.com", "www.chat.openai.com"):
            with self.subTest(host=host), patch.object(converter.urllib.request, "urlopen",
                return_value=self.response(json.dumps(self.conversation()).encode())
            ) as opened:
                result = converter.convert_source(f"http://{host}/share/synthetic-id?ignored=1#fragment")
                self.assertEqual(opened.call_args.args[0].full_url,
                                 "https://chatgpt.com/backend-api/share/synthetic-id")
                self.assertEqual(result[1]["source"], f"https://{host.removeprefix('www.')}/share/synthetic-id")

    def test_share_id_validation_and_encoding(self):
        for url in ("https://evil.example/share/id", "https://chatgpt.com/c/id",
                    "https://chatgpt.com.evil.example/share/id",
                    "https://chatgpt.com@evil.example/share/id",
                    "https://chatgpt.com/share/", "https://chatgpt.com/share/id/extra",
                    "https://chatgpt.com/share/../x", "https://chatgpt.com/share/%2Felsewhere",
                    "https://chatgpt.com/share/%2e%2e", "https://chatgpt.com/share/%0A",
                    "https://chatgpt.com/share/%5Celsewhere", "https://chatgpt.com/share/%7F"):
            with self.subTest(url=url), patch.object(converter.urllib.request, "urlopen") as opened:
                with self.assertRaises(ConvertError):
                    converter.fetch_share_json(url, 30)
                opened.assert_not_called()
        with patch.object(converter.urllib.request, "urlopen", return_value=self.response(
            json.dumps(self.conversation()).encode()
        )) as opened:
            converter.fetch_share_json("https://chatgpt.com/share/id%3Fvalue%23fragment/", 30)
            self.assertEqual(opened.call_args.args[0].full_url,
                             "https://chatgpt.com/backend-api/share/id%3Fvalue%23fragment")

    def test_cli_json_uses_filtered_metadata(self):
        conversation = self.conversation()
        conversation["linear_conversation"].append({"message": {
            "author": {"role": "assistant"}, "content": {"parts": ["hidden text"]},
            "metadata": {"is_visually_hidden_from_conversation": True}}})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "export.md"
            with patch.object(converter.urllib.request, "urlopen", return_value=self.response(
                json.dumps(conversation).encode()
            )), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(converter.main([self.URL, "-o", str(output), "--json"]), 0)
            metadata = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
            expected_markdown, expected_metadata = convert_html_to_markdown(self.html(conversation), self.URL)
            self.assertEqual(metadata, expected_metadata)
            self.assertEqual(output.read_text(encoding="utf-8"), expected_markdown)
            self.assertEqual(set(metadata), {"title", "slug", "source", "conversation_id",
                                             "created_at", "updated_at", "messages"})


class TestWebServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), WebHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_get_root(self):
        url = f"http://127.0.0.1:{self.port}/"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers.get("Content-Type", ""))
            body = resp.read().decode("utf-8")
            self.assertIn("ChatGPT vers Markdown", body)
            self.assertIn("id=\"url-input\"", body)

    def test_get_health(self):
        url = f"http://127.0.0.1:{self.port}/health"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")

    def test_get_robots_and_sitemap(self):
        robots_url = f"http://127.0.0.1:{self.port}/robots.txt"
        with urllib.request.urlopen(robots_url) as resp:
            self.assertEqual(resp.status, 200)
            content = resp.read().decode("utf-8")
            self.assertIn("User-agent: GPTBot", content)
            self.assertIn("User-agent: ClaudeBot", content)

        sitemap_url = f"http://127.0.0.1:{self.port}/sitemap.xml"
        with urllib.request.urlopen(sitemap_url) as resp:
            self.assertEqual(resp.status, 200)
            content = resp.read().decode("utf-8")
            self.assertIn("<urlset", content)

    def test_post_convert_html(self):
        url = f"http://127.0.0.1:{self.port}/api/convert"
        payload = json.dumps({"html": SAMPLE_REACT_ROUTER_HTML}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["success"])
            self.assertIn("# My Test Chat", data["markdown"])
            self.assertEqual(data["metadata"]["title"], "My Test Chat")

    def test_post_convert_url_uses_json_pipeline(self):
        source = "https://chatgpt.com/share/synthetic-id"
        conversation = {"linear_conversation": [{"message": {
            "author": {"role": "tool"}, "content": {"parts": ["Synthetic tool output"]}
        }}]}
        payload = json.dumps({"url": source, "include_tools": True}).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/convert",
            data=payload, headers={"Content-Type": "application/json"},
        )
        with patch.object(converter, "fetch_share_json", return_value=conversation) as fetched, \
                patch.object(converter, "fetch_html") as html_fetch:
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 200)
                data = json.loads(response.read())
        fetched.assert_called_once_with(source, 30)
        html_fetch.assert_not_called()
        self.assertTrue(data["success"])
        self.assertIn("Synthetic tool output", data["markdown"])
        self.assertEqual(data["metadata"]["messages"][0]["role"], "tool")

    def test_post_convert_invalid_url(self):
        url = f"http://127.0.0.1:{self.port}/api/convert"
        payload = json.dumps({"url": "https://google.com"}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req)
            self.fail("Expected HTTP 422 error")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 422)
            error_data = json.loads(exc.read().decode("utf-8"))
            self.assertFalse(error_data["success"])
            self.assertIn("Expected a public ChatGPT share URL", error_data["error"])


if __name__ == "__main__":
    unittest.main()
