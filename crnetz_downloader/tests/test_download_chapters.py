"""Run with python3 -m unittest discover -s tests -p test_download_chapters.py."""

from http.server import HTTPServer
import json
from pathlib import Path
import tempfile
import subprocess
import sys
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from download_chapters import make_handler, parse_chapters, decode_html, main


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.output = Path(self.directory.name)
        self.chapters = [{"name": "第一章", "url": "https://www.crnetz.com/127324/1.html"}]
        self.origin = "https://www.crnetz.com"
        self.server = HTTPServer(("127.0.0.1", 0), make_handler(
            self.chapters, self.output, self.origin, "test-token"
        ))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def request(self, path, data=None, origin=None, method=None):
        request = Request(self.base + path, data=data, method=method, headers={
            "Origin": origin or self.origin, "Content-Type": "text/html; charset=gbk"
        })
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, response.headers, response.read()

    def test_only_html_bytes_and_resume(self):
        data = b'<!doctype html><html><body onclick="putbookcase(127324, 1)">full original page\xff</body></html>'
        status, headers, body = self.request("/test-token/chapter/1", data)
        self.assertEqual(status, 200, body)
        self.assertEqual(headers["Access-Control-Allow-Origin"], self.origin)
        self.assertEqual((self.output / "0001.html").read_bytes(), data)
        self.assertEqual([p.name for p in self.output.iterdir()], ['0001.html'])
        status, _, body = self.request("/test-token/chapters")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), [])
        self.request("/test-token/chapter/1", b'<html>replacement</html>')
        self.assertEqual((self.output / "0001.html").read_bytes(), data)

    def test_multipage_resume_and_page_identity(self):
        first = '<meta charset="utf-8"><div id="content">(第1/3页)</div><a onclick="putbookcase(127324, 1)"></a>'
        data = first.encode('utf-8')
        self.request('/test-token/chapter/1', data)
        status, _, body = self.request('/test-token/chapters')
        pending = json.loads(body)
        self.assertEqual([item['url'] for item in pending], [
            self.origin + '/127324/1_2.html', self.origin + '/127324/1_3.html'])
        status, _, _ = self.request('/test-token/chapter/1/2', data)
        self.assertEqual(status, 400)
        for page in (2, 3):
            page_data = first.replace('第1/3页', f'第{page}/3页').encode('utf-8')
            status, _, body = self.request(f'/test-token/chapter/1/{page}', page_data)
            self.assertEqual(status, 200, body)
        _, _, body = self.request('/test-token/chapters')
        self.assertEqual(json.loads(body), [])
        self.assertEqual(sorted(p.name for p in self.output.iterdir()),
                         ['0001.html', '0001_2.html', '0001_3.html'])
        self.assertEqual((self.output / '0001.html').read_bytes(), data)

    def test_token_origin_and_path_guards(self):
        for path, origin in [("/wrong/chapter/1", self.origin),
                             ("/test-token/chapter/1", "https://example.com"),
                             ("/test-token/chapter/../../outside", self.origin),
                             ("/test-token/chapter/2", self.origin)]:
            with self.subTest(path=path, origin=origin):
                status, _, _ = self.request(path, b'<html>test</html>', origin)
                self.assertIn(status, [400, 403])
                self.assertEqual(list(self.output.iterdir()), [])
        status, headers, _ = self.request("/test-token/chapters", method="OPTIONS")
        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Origin"], self.origin)

    def test_challenge_rejected_and_user_file_preserved(self):
        status, _, _ = self.request("/test-token/chapter/1", b'<title>Just a moment...</title>')
        self.assertEqual(status, 400)
        self.assertEqual(list(self.output.iterdir()), [])
        existing = self.output / "0001.html"
        existing.write_bytes(b'user-owned file')
        status, _, _ = self.request("/test-token/chapter/1", b'<html>new file</html>')
        self.assertEqual(status, 400)
        self.assertEqual(existing.read_bytes(), b'user-owned file')
        status, _, _ = self.request("/test-token/chapters")
        self.assertEqual(status, 409)

    def test_browser_directory_initializes_and_resumes(self):
        chapters = []
        self.server.RequestHandlerClass = make_handler(
            chapters, self.output, self.origin, "test-token",
            "https://www.crnetz.com/127324/"
        )
        status, _, _ = self.request("/test-token/chapters")
        self.assertEqual(status, 409)
        directory = '<h2>正文</h2><a href="1.html">第一章</a>'.encode('gbk')
        status, _, body = self.request("/test-token/directory", directory)
        self.assertEqual(status, 200, body)
        self.assertEqual(chapters, self.chapters)
        self.request("/test-token/chapter/1", b'<html onclick="putbookcase(127324, 1)">chapter</html>')
        status, _, body = self.request("/test-token/chapters")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), [])
        # Running the snippet again rebuilds the directory, retaining HTML.
        self.request("/test-token/directory", directory)
        _, _, body = self.request("/test-token/chapters")
        self.assertEqual(json.loads(body), [])
        status, _, _ = self.request("/test-token/directory", b'<title>Just a moment...</title>')
        self.assertEqual(status, 400)
        self.assertEqual(chapters, self.chapters)

    def test_local_directory_cannot_be_replaced(self):
        status, _, _ = self.request("/test-token/directory", b'<html>other directory</html>')
        self.assertEqual(status, 400)

    def test_existing_other_chapter_is_not_skipped_or_overwritten(self):
        path = self.output / '0001.html'
        data = b'<html onclick="putbookcase(999, 1)">other book</html>'
        path.write_bytes(data)
        status, _, _ = self.request('/test-token/chapters')
        self.assertEqual(status, 409)
        status, _, _ = self.request('/test-token/chapter/1', b'<html>replacement</html>')
        self.assertEqual(status, 400)
        self.assertEqual(path.read_bytes(), data)


class MarkdownTests(unittest.TestCase):
    def test_multipage_merge_and_missing_page_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = Path(__file__).resolve().parents[1]
            for name in ('html_to_md.py', 'download_chapters.py'):
                (root / name).write_bytes((source / name).read_bytes())
            html_dir = root / 'chapter_html'
            html_dir.mkdir()
            template = '<a href="/123/" title="测试书">测试书</a><h1 class="title">第二章</h1><div class="content" id="content">第二章 (第{page}/2页)<br>{body}<br>（本章未完，请点击下一页继续阅读）</div>'
            (html_dir / '0002.html').write_text(template.format(page=1, body='首页正文'), encoding='utf-8')
            command = [sys.executable, str(root / 'html_to_md.py')]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('missing pages: [2]', result.stderr)
            self.assertFalse((root / 'md').exists())
            (html_dir / '0002_2.html').write_text(template.format(page=2, body='续页正文'), encoding='utf-8')
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = (root / 'md/测试书.md').read_text(encoding='utf-8')
            self.assertEqual(text.count('## 第二章'), 1)
            self.assertIn('首页正文', text)
            self.assertIn('续页正文', text)
            self.assertLess(text.index('首页正文'), text.index('续页正文'))
            self.assertNotIn('(第1/2页)', text)
            self.assertNotIn('(第2/2页)', text)
            self.assertNotIn('（本章未完，请点击下一页继续阅读）', text)


class DirectoryTests(unittest.TestCase):
    def test_main_directory_order_and_links(self):
        html = '''<h2>最新章节</h2><a href="3.html">第三章</a>
        <h2>某书正文</h2><a href="1.html">第一章 &amp; 开始</a>
        <a href="/127324/2.html"><span>第二章</span></a>
        <a href="3.html">第三章</a><a href="3.html#top">重复</a>
        <a href="/another/4.html">其他书</a>
        <a href="https://example.com/127324/4.html">其他网站</a>'''
        chapters = parse_chapters(html)
        self.assertEqual([c['name'] for c in chapters], ['第一章 & 开始', '第二章', '第三章'])
        self.assertEqual(chapters[1]['url'], 'https://www.crnetz.com/127324/2.html')

    def test_gbk_and_dt_headings(self):
        html = '<meta charset="gbk"><dl><dt>正文</dt><dd><a href="1.html">第一章</a></dd></dl>'
        chapters = parse_chapters(decode_html(html.encode('gbk')))
        self.assertEqual(chapters[0]['name'], '第一章')

    def test_missing_directory_is_error(self):
        with self.assertRaisesRegex(ValueError, '未找到正文目录'):
            parse_chapters('<h1>Access denied</h1>')

    def test_cli_html_does_not_read_external_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            html = root / 'page.html'
            html.write_text('<h2>正文</h2><a href="1.html">第一章</a>', encoding='utf-8')
            with patch('download_chapters.HTTPServer') as server:
                server.return_value.__enter__.return_value.server_port = 8765
                with patch('download_chapters.make_handler') as handler:
                    self.assertEqual(main(['https://www.crnetz.com/127324', '--html', str(html), '-o', str(root/'out')]), 0)
                    chapters, _, origin, _, directory_url = handler.call_args.args
                    self.assertEqual(chapters[0]['url'], 'https://www.crnetz.com/127324/1.html')
                    self.assertEqual(origin, 'https://www.crnetz.com')
                    self.assertIsNone(directory_url)

    def test_cli_url_defers_directory_to_chrome(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('download_chapters.HTTPServer') as server:
                server.return_value.__enter__.return_value.server_port = 8765
                with patch('download_chapters.make_handler') as handler:
                    self.assertEqual(main(['https://www.crnetz.com/127324/', '-o', directory]), 0)
                    self.assertEqual(handler.call_args.args[0], [])
                    self.assertEqual(handler.call_args.args[-1], 'https://www.crnetz.com/127324/')


if __name__ == "__main__":
    unittest.main()
