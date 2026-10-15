import re
from pathlib import Path
from html.parser import HTMLParser

from download_chapters import pagination, decode_html


class Reader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.skip = 0
        self.heading = False
        self.title = []
        self.body = []
        self.book: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        a = dict(attrs)
        if (
            tag == "a"
            and re.fullmatch(r"/\d+/", a.get("href") or "")
            and a.get("title")
        ):
            self.book = a["title"]
        if tag == "h1" and "title" in (a.get("class") or "").split():
            self.heading = True
        if (
            tag == "div"
            and a.get("id") == "content"
            and "content" in (a.get("class") or "").split()
        ):
            self.depth = 1
        elif self.depth and tag == "div":
            self.depth += 1
        if self.depth:
            if tag in ("script", "style"):
                self.skip += 1
            elif tag in ("br", "p") and not self.skip:
                self.body.append("\n")

    def handle_endtag(self, tag):
        if tag == "h1":
            self.heading = False
        if self.depth:
            if tag in ("script", "style"):
                self.skip -= 1
            elif tag == "div":
                self.depth -= 1
            elif tag == "p" and not self.skip:
                self.body.append("\n")

    def handle_data(self, data):
        if self.heading:
            self.title.append(data)
        if self.depth and not self.skip:
            self.body.append(data)


def escape(text):
    return re.sub(r"([\\`*_{}\[\]<>#|])", r"\\\1", text)


root = Path(__file__).resolve().parent
files = sorted(
    (root / "chapter_html").glob("*.html"),
    key=lambda p: (
        tuple(map(int, p.stem.split("_")))
        if "_" in p.stem
        else (int(p.stem), 1)
    ),
)
chapters = []
book = None
last_chapter = None
for path in files:
    chapter_index = int(path.stem.split("_")[0])
    page = int(path.stem.split("_")[1]) if "_" in path.stem else 1
    marker = pagination(path.read_bytes())
    if marker:
        if marker[0] != page:
            raise ValueError(f"Page mismatch: {path}")
        missing = [
            number
            for number in range(1, marker[1] + 1)
            if not (
                path.parent
                / (
                    f"{chapter_index:04d}"
                    + (f"_{number}" if number > 1 else "")
                    + ".html"
                )
            ).exists()
        ]
        if missing:
            raise ValueError(
                f"Incomplete chapter {chapter_index}, missing pages: {missing}"
            )
    reader = Reader()
    reader.feed(decode_html(path.read_bytes()))
    title = "".join(reader.title).strip()
    paragraphs = [
        line.strip()
        for line in "".join(reader.body).splitlines()
        if line.strip()
    ]
    page_title = re.compile(
        re.escape(title) + r"\s*[（(]\s*第\s*\d+\s*/\s*\d+\s*页\s*[）)]"
    )
    continuation = re.compile(
        r"[（(]\s*本章未完\s*[，,]\s*请点击下一页继续阅读\s*[）)]"
    )
    paragraphs = [
        line
        for line in paragraphs
        if not page_title.fullmatch(line) and not continuation.fullmatch(line)
    ]
    if not reader.book or not title or not paragraphs:
        raise ValueError(f"Missing book/title/content: {path}")
    if book and book != reader.book:
        raise ValueError(f"Book mismatch: {path}")
    book = reader.book
    body = "\n\n".join(map(escape, paragraphs))
    if chapter_index == last_chapter:
        chapters[-1] += "\n\n" + body
    else:
        chapters.append("## " + escape(title) + "\n\n" + body)
    last_chapter = chapter_index
if book is None:
    raise ValueError("No chapters found in chapter_html")
output_dir = root / "md"
output_dir.mkdir(parents=True, exist_ok=True)
output = output_dir / (book + ".md")
output.write_text(
    "# " + escape(book) + "\n\n" + "\n\n".join(chapters) + "\n",
    encoding="utf-8",
)
print(f"{len(chapters)} chapters ({len(files)} pages) -> {output}")
print(f"{output.stat().st_size} bytes")
