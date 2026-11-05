"""Tests for chatgpt_share_md converter and web server."""

import json
import threading
import urllib.request
import unittest
from http.server import HTTPServer

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
