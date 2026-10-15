#!/usr/bin/env python3
"""Parse a book directory and receive chapter HTML from an existing Chrome session.

Use the browser to fetch the directory (also works when HTTP requests get 403):
    python3 download_chapters.py https://www.crnetz.com/127324/

Use a saved directory HTML; the URL resolves relative chapter links:
    python3 download_chapters.py https://www.crnetz.com/127324/ --html page.html

Open the printed localhost URL and run its snippet in a chapter/directory tab
in your normal Chrome. Only the Python standard library is required. HTML is
saved as original response bytes; linked resources are not downloaded.
The output directory is cleared on startup, including when using --output.
Only HTML files are written. Within the same server session, resume checks the page's book/chapter bookmark
IDs and page numbers before skipping an existing file. Missing continuation
pages are discovered from the current/total page marker and saved separately
as 0001_2.html, 0001_3.html, etc.
"""

import re
import sys
import json
import shutil
import secrets
import argparse
from html import escape
from pathlib import Path
from html.parser import HTMLParser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urljoin, urlsplit


DEFAULT_URL = "https://www.crnetz.com/127324/"


def validate_html(status, content_type, data):
    sample = data[:65536].lower()
    if b"<title>just a moment" in sample or b"cf-chl-" in sample:
        raise ValueError(
            "收到 Cloudflare 验证页, 请在正常 Chrome 中完成验证后重试"
        )
    if not 200 <= status < 300:
        raise ValueError(f"HTTP {status}")
    if not data or "html" not in content_type.lower():
        raise ValueError("响应为空或 Content-Type 不是 HTML")


class ChapterParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.book = urlsplit(base_url)
        self.chapter_path = re.compile(
            re.escape(self.book.path.rstrip("/") + "/") + r"\d+\.html$"
        )
        self.in_body = False
        self.heading = None
        self.heading_text = []
        self.anchor_url = None
        self.anchor_text = []
        self.chapters = []
        self.seen = set()

    def handle_starttag(self, tag, attrs):
        if tag in {"dt", "h1", "h2", "h3"}:
            self.heading = tag
            self.heading_text = []
        if tag == "a":
            self.anchor_url = dict(attrs).get("href")
            self.anchor_text = []

    def handle_data(self, data):
        if self.heading:
            self.heading_text.append(data)
        if self.anchor_url is not None:
            self.anchor_text.append(data)

    def handle_endtag(self, tag):
        if tag == self.heading:
            title = "".join(self.heading_text).strip()
            if title.endswith("正文"):
                self.in_body = True
            elif self.in_body:
                self.in_body = False
            self.heading = None
        if tag != "a" or self.anchor_url is None:
            return
        url = urljoin(self.base_url, self.anchor_url)
        parts = urlsplit(url)
        name = "".join(self.anchor_text).strip()
        if (
            self.in_body
            and name
            and parts.scheme in {"http", "https"}
            and parts.netloc == self.book.netloc
            and self.chapter_path.fullmatch(parts.path)
        ):
            url = parts._replace(fragment="", query="").geturl()
            if url not in self.seen:
                self.chapters.append({"name": name, "url": url})
                self.seen.add(url)
        self.anchor_url = None
        self.anchor_text = []


def decode_html(data, charset=None):
    """Honor declared encoding, replacing malformed bytes as browsers do."""
    if not charset:
        match = re.search(rb"charset\s*=\s*[\"']?([\w-]+)", data[:8192], re.I)
        charset = match.group(1).decode("ascii") if match else "utf-8"
    return data.decode(charset, errors="replace")


def parse_chapters(html, base_url=DEFAULT_URL):
    """Return chapters in main-directory order, excluding the latest list."""
    parser = ChapterParser(base_url)
    parser.feed(html)
    parser.close()
    if not parser.chapters:
        raise ValueError(
            "未找到正文目录章节, 请检查是否为目录页面或网站结构已变化"
        )
    return parser.chapters


def pagination(data):
    """Return the site's explicit current/total page marker, if present."""
    try:
        text = decode_html(data)
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    match = re.search(r"第\s*(\d+)\s*/\s*(\d+)\s*页", text)
    if not match:
        return None
    current, total = map(int, match.groups())
    if not 1 <= current <= total <= 1000:
        raise ValueError("无效章节分页标记")
    return current, total


def browser_script(endpoint, origin, directory_url=None):
    return (
        """(async () => {
  const endpoint = ENDPOINT;
  const directoryUrl = DIRECTORY_URL;
  if (location.origin !== ORIGIN) throw new Error('请在已打开目录或正文的小说网站标签页运行');
  if (window.crnetzDownloading) throw new Error('下载已在运行');
  window.crnetzDownloading = true;
  window.stopChapterDownload = () => { window.crnetzDownloading = false; };
  async function local(path, options = {}) {
    const response = await fetch(endpoint + path, {
      ...options, credentials: 'omit', signal: AbortSignal.timeout(30000)
    });
    if (!response.ok) throw new Error('本地保存失败: ' + await response.text());
    return response.json();
  }
  async function fetchHtml(url) {
    const response = await fetch(url, {
      credentials: 'same-origin', signal: AbortSignal.timeout(30000)
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${url}, 已停止`);
    const bytes = await response.arrayBuffer();
    const preview = new TextDecoder().decode(bytes.slice(0, 65536)).toLowerCase();
    if (preview.includes('<title>just a moment') || preview.includes('cf-chl-')) {
      throw new Error('遇到验证页, 已停止; 请手动打开该 URL 完成验证后重新运行: ' + url);
    }
    return {bytes, contentType: response.headers.get('content-type') || ''};
  }
  try {
    if (directoryUrl) {
      const directory = await fetchHtml(directoryUrl);
      await local('/directory', {
        method: 'POST', headers: { 'Content-Type': directory.contentType }, body: directory.bytes
      });
    }
    while (window.crnetzDownloading) {
      const chapters = await local('/chapters');
      if (!chapters.length) break;
      for (const chapter of chapters) {
        if (!window.crnetzDownloading) break;
        const chapterHtml = await fetchHtml(chapter.url);
        await local('/chapter/' + chapter.index + '/' + chapter.page, {
          method: 'POST', headers: { 'Content-Type': chapterHtml.contentType }, body: chapterHtml.bytes
        });
        console.log(`已保存 ${chapter.index} 第 ${chapter.page} 页: ${chapter.name}`);
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
    }
    console.log(window.crnetzDownloading ? '章节下载完成' : '下载已停止');
  } catch (error) {
    console.error('下载停止:', error);
  } finally {
    window.crnetzDownloading = false;
  }
})();
""".replace("ENDPOINT", json.dumps(endpoint))
        .replace("ORIGIN", json.dumps(origin))
        .replace("DIRECTORY_URL", json.dumps(directory_url))
    )


class _ChapterHandler(BaseHTTPRequestHandler):
    chapters: list[dict[str, str]]
    output: Path
    origin: str
    token: str
    directory_url: str | None

    def record(self, index, page=1):
        chapter = self.chapters[index - 1]
        suffix = "" if page == 1 else f"_{page}"
        url = chapter["url"].removesuffix(".html") + suffix + ".html"
        return {
            "index": index,
            "page": page,
            "name": chapter["name"],
            "url": url,
            "file": f"{index:04d}_{page}.html",
        }

    def check_identity(self, data, index, page):
        ids = re.fullmatch(
            r"/(\d+)/(\d+)\.html",
            urlsplit(self.chapters[index - 1]["url"]).path,
        )
        bookmarks = re.findall(rb"putbookcase\(\s*(\d+)\s*,\s*(\d+)\s*\)", data)
        marker = pagination(data)
        if (
            not ids
            or tuple(value.encode("ascii") for value in ids.groups())
            not in bookmarks
        ):
            raise ValueError("HTML 的书籍或章节标识不匹配")
        if (marker and marker[0] != page) or (page > 1 and not marker):
            raise ValueError("HTML 的分页标识不匹配")

    def completed(self, index, page=1):
        item = self.record(index, page)
        path = self.output / item["file"]
        if not path.exists():
            return False
        data = path.read_bytes()
        validate_html(200, "text/html", data)
        try:
            self.check_identity(data, index, page)
        except ValueError as exc:
            raise ValueError(
                f"已有 HTML 标识不匹配, 拒绝覆盖: {path.name}: {exc}"
            ) from exc
        return True

    def pending_pages(self):
        """Return missing pages of the first unfinished chapter only."""
        pending = []
        for index in range(1, len(self.chapters) + 1):
            page, total = 1, 1
            while page <= total:
                item = self.record(index, page)
                if self.completed(index, page):
                    marker = pagination(
                        (self.output / item["file"]).read_bytes()
                    )
                    if marker:
                        total = max(total, marker[1])
                else:
                    pending.append(item)
                page += 1
            if pending:
                return pending
        return pending

    def log_message(self, format: str, *args: object) -> None:
        pass  # Do not log the session token in URLs.

    def allowed(self):
        return self.headers.get(
            "Origin"
        ) == self.origin and self.path.startswith(f"/{self.token}/")

    def respond(
        self, status, body, content_type="application/json; charset=utf-8"
    ):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.headers.get("Origin") == self.origin:
            self.send_header("Access-Control-Allow-Origin", self.origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        if not self.allowed():
            self.respond(403, "Origin or token rejected")
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path == f"/{self.token}/":
            # The copy page contains no external scripts or website data.
            server = self.server
            assert isinstance(server, HTTPServer)
            endpoint = f"http://127.0.0.1:{server.server_port}/{self.token}"
            script = escape(
                browser_script(endpoint, self.origin, self.directory_url)
            )
            page = (
                '<!doctype html><meta charset="utf-8"><title>章节下载</title>'
            )
            page += "<h1>在已有 Chrome 会话中下载章节</h1>"
            page += "<p>复制下方代码。在已打开目录或正文的小说标签页中按 F12，进入 Sources → Snippets，新建 Snippet，粘贴代码，按 Ctrl+Enter 执行。</p>"
            page += "<p>若 Chrome 询问是否允许访问本地网络，请允许。保持标签页打开。停止下载可在 Console 执行 stopChapterDownload()。</p>"
            page += f'<textarea readonly style="width:95%;height:70vh">{script}</textarea>'
            self.respond(200, page, "text/html; charset=utf-8")
            return
        if not self.allowed() or self.path != f"/{self.token}/chapters":
            self.respond(403, "Origin, token or path rejected")
            return
        try:
            if not self.chapters:
                raise ValueError("目录尚未解析, 请先运行浏览器代码片段")
            pending = self.pending_pages()
            self.respond(200, json.dumps(pending, ensure_ascii=False))
        except (OSError, ValueError, LookupError) as exc:
            self.respond(409, str(exc))

    def read_html(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 20 * 1024 * 1024:
            raise ValueError("HTML 大小必须在 1 byte 到 20 MiB 之间")
        self.connection.settimeout(30)
        data = self.rfile.read(length)
        if len(data) != length:
            raise ValueError("HTML 传输不完整")
        validate_html(200, self.headers.get("Content-Type", ""), data)
        return data

    def receive_directory(self, data):
        if self.directory_url is None:
            raise ValueError("本地 HTML 模式不接受替换目录")
        charset_match = re.search(
            r"charset\s*=\s*[\"']?([\w-]+)",
            self.headers.get("Content-Type", ""),
            re.I,
        )
        charset = charset_match.group(1) if charset_match else None
        parsed = parse_chapters(decode_html(data, charset), self.directory_url)
        self.chapters[:] = parsed
        print(f"已解析目录: {len(self.chapters)} 章", flush=True)
        self.respond(200, json.dumps({"chapters": len(self.chapters)}))

    def receive_chapter(self, data):
        match = re.fullmatch(
            re.escape(f"/{self.token}/chapter/") + r"([0-9]+)(?:/([0-9]+))?",
            self.path,
        )
        if not match:
            raise ValueError("无效章节序号")
        index, page = int(match[1]), int(match[2] or 1)
        if not 1 <= index <= len(self.chapters) or not 1 <= page <= 1000:
            raise ValueError("章节序号或页码超出范围")
        if self.completed(index, page):
            self.respond(200, '{"status":"skipped"}')
            return
        self.check_identity(data, index, page)
        if page > 1:
            if not self.completed(index):
                raise ValueError("请先保存章节首页")
            marker = pagination(
                (self.output / self.record(index)["file"]).read_bytes()
            )
            if not marker or page > marker[1]:
                raise ValueError("页码超出章节分页范围")
        item = self.record(index, page)
        path = self.output / item["file"]
        temporary = path.with_suffix(".html.part")
        temporary.write_bytes(data)
        temporary.replace(path)
        print(
            f"[{index}/{len(self.chapters)}] 已保存 {path.name}: {item['name']} ({len(data)} bytes)",
            flush=True,
        )
        self.respond(200, '{"status":"saved"}')

    def do_POST(self):
        if not self.allowed():
            self.respond(403, "Origin or token rejected")
            return
        try:
            data = self.read_html()
            if self.path == f"/{self.token}/directory":
                self.receive_directory(data)
            else:
                self.receive_chapter(data)
        except (OSError, ValueError, LookupError) as exc:
            self.respond(400, str(exc))


def make_handler(chapters, output, origin, token, directory_url=None):
    class Handler(_ChapterHandler):
        pass

    Handler.chapters = chapters
    Handler.output = output
    Handler.origin = origin
    Handler.token = token
    Handler.directory_url = directory_url
    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="解析目录并通过已有 Chrome 会话下载完整章节 HTML"
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=DEFAULT_URL,
        help="小说目录 URL, 用于解析相对链接",
    )
    parser.add_argument(
        "--html", type=Path, help="本地目录 HTML, 无需浏览器再次获取目录"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "chapter_html",
        help="HTML 输出目录, 启动时清空已有内容 (默认: 脚本同目录下的 chapter_html)",
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        parts = urlsplit(args.url)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.netloc
            or not re.fullmatch(r"/\d+/?", parts.path)
        ):
            raise ValueError(
                "请输入小说目录 URL, 例如 https://www.crnetz.com/127324/"
            )
        directory_url = parts._replace(
            path=parts.path.rstrip("/") + "/", query="", fragment=""
        ).geturl()
        origin = f"{parts.scheme}://{parts.netloc}"
        chapters = (
            parse_chapters(decode_html(args.html.read_bytes()), directory_url)
            if args.html
            else []
        )
        if args.output.is_symlink():
            raise ValueError("输出目录不能是符号链接")
        args.output.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(24)
        handler = make_handler(
            chapters,
            args.output,
            origin,
            token,
            None if args.html else directory_url,
        )
        with HTTPServer(("127.0.0.1", args.port), handler) as server:
            for path in args.output.iterdir():
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            print(
                f"请用 Windows Chrome 打开: http://127.0.0.1:{server.server_port}/{token}/",
                flush=True,
            )
            source = (
                f"已解析本地目录: {len(chapters)} 章"
                if args.html
                else "等待 Chrome 获取并解析目录"
            )
            print(
                f"输出目录: {args.output.resolve()} | {source} | Ctrl+C 停止服务",
                flush=True,
            )
            server.serve_forever()
    except KeyboardInterrupt:
        print("接收服务已停止, 已保存章节保留.")
    except (OSError, ValueError, LookupError) as exc:
        print(f"启动失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
