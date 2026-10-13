from html.parser import HTMLParser
from pathlib import Path
import re

class Reader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.skip = 0
        self.heading = False
        self.title = []
        self.body = []
        self.book = None
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'a' and re.fullmatch(r'/\d+/', a.get('href', '')) and a.get('title'):
            self.book = a['title']
        if tag == 'h1' and 'title' in a.get('class', '').split():
            self.heading = True
        if tag == 'div' and a.get('id') == 'content' and 'content' in a.get('class', '').split():
            self.depth = 1
        elif self.depth and tag == 'div':
            self.depth += 1
        if self.depth:
            if tag in ('script', 'style'):
                self.skip += 1
            elif tag in ('br', 'p') and not self.skip:
                self.body.append('\n')
    def handle_endtag(self, tag):
        if tag == 'h1':
            self.heading = False
        if self.depth:
            if tag in ('script', 'style'):
                self.skip -= 1
            elif tag == 'div':
                self.depth -= 1
            elif tag == 'p' and not self.skip:
                self.body.append('\n')
    def handle_data(self, data):
        if self.heading:
            self.title.append(data)
        if self.depth and not self.skip:
            self.body.append(data)

def escape(text):
    return re.sub(r'([\\`*_{}\[\]<>#|])', r'\\\1', text)

root = Path(__file__).resolve().parent
files = sorted((root / 'chapter_html').glob('*.html'), key=lambda p: int(p.stem))
chapters = []
book = None
for path in files:
    reader = Reader()
    reader.feed(path.read_text(encoding='utf-8'))
    title = ''.join(reader.title).strip()
    paragraphs = [line.strip() for line in ''.join(reader.body).splitlines() if line.strip()]
    if not reader.book or not title or not paragraphs:
        raise ValueError(f'Missing book/title/content: {path}')
    if book and book != reader.book:
        raise ValueError(f'Book mismatch: {path}')
    book = reader.book
    chapters.append('## ' + escape(title) + '\n\n' + '\n\n'.join(map(escape, paragraphs)))
output_dir = root / 'md'
output_dir.mkdir(parents=True, exist_ok=True)
output = output_dir / (book + '.md')
if output.exists():
    raise FileExistsError(output)
output.write_text('# ' + escape(book) + '\n\n' + '\n\n'.join(chapters) + '\n', encoding='utf-8')
print(f'{len(files)} chapters -> {output}')
print(f'{output.stat().st_size} bytes')
