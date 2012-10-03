# coding=utf-8
from flask import Flask, g, render_template, current_app, request, redirect, abort, url_for
from jinja2.utils import Markup
from werkzeug.routing import BaseConverter, ValidationError
from werkzeug.datastructures import MultiDict
from contextlib import contextmanager
from collections import namedtuple
import re
import sqlite3
import urllib
import mappings

app = Flask(__name__, static_folder='res', template_folder='tmpl')

@app.template_filter('classes')
def filter_classes(v):
    if not v: return u''
    return Markup(u' class="%s"') % u' '.join(v)

@app.template_filter('htmltext')
def filter_htmltext(s, markup=None, query=None):
    if not s: return u''

    if markup is not None:
        markup = map(ord, markup)
    else:
        markup = [0] * len(s)

    # flags:
    # 1 -- Capitalized
    # 2 -- UPPERCASED
    # 128 -- italicized (artificial text in KJV)
    # 256 -- highlighted

    # add a pseudo markup flag (256) for query highlighting
    if query:
        pos = -1
        while True:
            pos = s.find(query, pos+1)
            if pos < 0: break
            for i in xrange(pos, pos+len(query)):
                markup[i] |= 256

    ss = []
    cur = []
    prevflags = 0
    for ch, flags in zip(s, markup) + [(u'', None)]:
        if flags is None or flags != prevflags:
            ss.append(Markup().join(cur))
            cur = []

            closing = []
            opening = []

            flags = flags or 0
            changed = (prevflags ^ flags)
            cascade = False
            if cascade or changed & 256:
                if prevflags & 256: closing.append(Markup('</mark>'))
                if flags & 256: opening.append(Markup('<mark>'))
                cascade = True
            if cascade or changed & 128:
                if prevflags & 128: closing.append(Markup('</i>'))
                if flags & 128: opening.append(Markup('<i>'))
                cascade = True
            if cascade or changed & 2:
                if prevflags & 2: closing.append(Markup('</strong>'))
                if flags & 2: opening.append(Markup('<strong>'))
                cascade = True
            if cascade or changed & 1:
                if prevflags & 1: closing.append(Markup('</em>'))
                if flags & 1: opening.append(Markup('<em>'))
                cascade = True

            prevflags = flags
            ss.extend(closing[::-1])
            ss.extend(opening)

        cur.append(ch)

    return Markup().join(ss)

@contextmanager
def database():
    db = sqlite3.connect('bible.db')
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()

class Normalizable(namedtuple('Normalizable', 'before after')):
    def __str__(self): return str(self.after)
    def __unicode__(self): return unicode(self.after)
    def __getattr__(self, name): return getattr(self.after, name)

sqlite3.register_adapter(mappings.Entry, str)
sqlite3.register_adapter(Normalizable, str)

class BookConverter(BaseConverter):
    def to_python(self, value):
        try:
            return Normalizable(value, mappings.books.from_any(value))
        except KeyError:
            raise ValidationError()

    def to_url(self, value):
        return str(value)

app.url_map.converters['book'] = BookConverter

def book_index(b):
    return mappings.books.indices[str(b)]

def build_query_suffix(*exclude):
    normalized_version = str(g.version1) + (','+str(g.version2) if g.version2 else '')
    newquery = MultiDict(request.args)
    if normalized_version and normalized_version != mappings.DEFAULT_VER:
        newquery['v'] = normalized_version
    else:
        newquery.poplist('v')
    kvs = [(k, v.encode('utf-8')) for k,v in newquery.items(multi=True) if k not in exclude]
    newquery = urllib.urlencode(kvs)
    if newquery:
        return '?' + newquery
    else:
        return ''

def normalize_url(self, **kwargs):
    orig_version = request.args.get('v', '')
    v1, _, v2 = orig_version.partition(',')
    try:
        g.version1 = mappings.versions.from_any(v1)
    except Exception:
        g.version1 = mappings.versions.from_code(mappings.DEFAULT_VER)
    try:
        g.version2 = mappings.versions.from_any(v2)
        if g.version1 == g.version2: g.version2 = None
    except Exception:
        g.version2 = None
    normalized_version = str(g.version1) + (','+str(g.version2) if g.version2 else '')
    if normalized_version == mappings.DEFAULT_VER: normalized_version = ''

    need_redirect = (orig_version != normalized_version)
    normalized_kwargs = {}
    for k, v in kwargs.items():
        if isinstance(v, Normalizable):
            after = unicode(v.after).encode('utf-8')
            before = unicode(v.before).encode('utf-8')
            normalized_kwargs[k] = after
            need_redirect = need_redirect or after != before
        else:
            normalized_kwargs[k] = str(v).encode('utf-8')

    if need_redirect:
        abort(redirect(url_for(self, **normalized_kwargs) + build_query_suffix()))

def render_verses(tmpl, verses, **kwargs):
    query = kwargs.get('query', None)
    highlight = kwargs.get('highlight', None)

    prev = None
    prevhl = False
    rows = []
    tbodys = []
    for verse in verses:
        hl = highlight(verse['book'], verse['chapter'], verse['verse']) if highlight else False
        if prevhl != hl:
            sclasses = []
            if prevhl: sclasses.append('highlight')
            if rows: tbodys.append({'classes': sclasses, 'verses': rows})
            rows = []
            prevhl = hl

        text = verse['text']
        markup = verse['markup']
        prefix = u''
        vclasses = []
        if (verse['book'], verse['chapter'], verse['verse']-1) == prev:
            vclasses.append('cont')
        rows.append({
            'book': mappings.books[verse['book']],
            'chapter': verse['chapter'],
            'classes': vclasses,
            'verse': verse['verse'],
            'prefix': prefix,
            'text': text,
            'markup': markup,
            'text2': verse['text2'] if 'text2' in verse.keys() else None,
            'markup2': verse['markup2'] if 'markup2' in verse.keys() else None,
        })
        prev = (verse['book'], verse['chapter'], verse['verse'])
    if rows:
        sclasses = []
        if prevhl: sclasses.append('highlight')
        tbodys.append({'classes': sclasses, 'verses': rows})

    return render_template(tmpl, version1=g.version1, version2=g.version2,
                           sections=tbodys, **kwargs)

def execute_verses_query(db, where='1', args=()):
    if g.version2:
        return db.execute('''
            select v.*, d1.text as text,  d1.markup as markup,
                        d2.text as text2, d2.markup as markup2
            from verses v inner join data d1 on v.ordinal=d1.ordinal
                          inner join data d2 on v.ordinal=d2.ordinal
            where d1.version=? and d2.version=? and '''+where+'''
            order by ordinal asc;
        ''', (g.version1, g.version2) + args)
    else:
        return db.execute('''
            select v.*, d.text as text, d.markup as markup
            from verses v inner join data d on v.ordinal=d.ordinal
            where d.version=? and '''+where+'''
            order by ordinal asc;
        ''', (g.version1,) + args)


@app.route('/')
def index():
    return render_template('index.html', books=mappings.books)

@app.route('/+/about')
def about():
    return render_template('about.html')

@app.route('/search')
def search():
    query = request.args['q'].strip()
    if not query: return redirect('/')

    normalize_url('.search')

    # try to redirect to direct links
    books = ur'(?:%s)' % u'|'.join(book.ko for book in mappings.books)
    m = re.search(ur'^\s*(%s)\s*(?:(\d+:\d+)(?:[-~](\d+(?::\d+)?))?'
                               ur'|(\d+)(?:[-~](\d+))?)\s*$' % books, query)
    if m:
        book = mappings.books.from_value(m.group(1))
        if m.group(2) is not None:
            chap1, _, verse1 = m.group(2).partition(u':')
            chap1 = int(chap1)
            verse1 = int(verse1)
            if m.group(3) is not None:
                chap2, _, verse2 = m.group(3).rpartition(u':')
                chap2 = int(chap2 or chap1)
                verse2 = int(verse2)
                url = url_for('.view_verses', book=book, chapter1=chap1, verse1=verse1,
                                                         chapter2=chap2, verse2=verse2)
            else:
                url = url_for('.view_verse', book=book, chapter=chap1, verse=verse1)
        else:
            chap1 = int(m.group(4))
            if m.group(5) is not None:
                chap2 = int(m.group(5))
                url = url_for('.view_chapters', book=book, chapter1=chap1, chapter2=chap2)
            else:
                url = url_for('.view_chapter', book=book, chapter=chap1)
        return redirect(url + build_query_suffix('q'))

    try:
        book = mappings.books.from_value(query)
    except KeyError:
        book = None
    if book:
        return redirect(url_for('.view_book', book=book))

    with database() as db:
        verses = execute_verses_query(db, '"text" like ?',
                ('%%%s%%' % query.strip(),)).fetchall()

    return render_verses('search.html', verses, query=query)

@app.route('/<book:book>/')
def view_book(book):
    return redirect(url_for('.view_chapter', book=book, chapter=1))

@app.route('/<book:book>/<int:chapter>')
def view_chapter(book, chapter):
    normalize_url('.view_chapter', book=book, chapter=chapter)

    with database() as db:
        verses = execute_verses_query(db, 'v.book=? and v.chapter=?',
                (book_index(book), chapter)).fetchall()

    return render_verses('chapters.html', verses,
                         book=book, chapter1=chapter, chapter2=chapter)

@app.route('/<book:book>/<int:chapter1>-<int:chapter2>')
def view_chapters(book, chapter1, chapter2):
    normalize_url('.view_chapters', book=book, chapter1=chapter1, chapter2=chapter2)

    with database() as db:
        verses = execute_verses_query(db, 'v.book=? and v.chapter between ? and ?',
                (book_index(book), chapter1, chapter2)).fetchall()

    return render_verses('chapters.html', verses,
                         book=book, chapter1=chapter1, chapter2=chapter2)

def do_view_verses(book, chapter1, verse1, chapter2, verse2, highlight=None):
    with database() as db:
        verses = execute_verses_query(db,
                '''v.book=? and (v.chapter>? or (v.chapter=? and v.verse>=?)) and
                                (v.chapter<? or (v.chapter=? and v.verse<=?))''',
                (book_index(book), chapter1, chapter1, verse1,
                                   chapter2, chapter2, verse2)).fetchall()

    return render_verses('verses.html', verses, highlight=highlight,
                         book=book, chapter1=chapter1, verse1=verse1,
                         chapter2=chapter2, verse2=verse2)

@app.route('/<book:book>/<int:chapter>.<int:verse>')
def view_verse(book, chapter, verse):
    normalize_url('.view_verse', book=book, chapter=chapter, verse=verse)

    booknum = book_index(book)
    highlight = lambda b,c,v: b==booknum and (c,v)==(chapter,verse)
    return do_view_verses(book, chapter, verse-5, chapter, verse+5, highlight)

@app.route('/<book:book>/<int:chapter1>.<int:verse1>-<int:chapter2>.<int:verse2>')
def view_verses(book, chapter1, verse1, chapter2, verse2):
    normalize_url('.view_verses', book=book, chapter1=chapter1, verse1=verse1,
                  chapter2=chapter2, verse2=verse2)

    booknum = book_index(book)
    highlight = lambda b,c,v: b==booknum and (chapter1,verse1)<=(c,v)<=(chapter2,verse2)
    return do_view_verses(book, chapter1, verse1-5, chapter2, verse2+5, highlight)

@app.before_request
def compile_less():
    if current_app.debug:
        import sys, os, os.path, subprocess
        path = app.static_folder
        entrypoint = os.path.join(path, 'style.less')
        combined = os.path.join(path, 'style.css')
        combinedtime = os.stat(combined).st_mtime
        if any(os.stat(os.path.join(path, f)).st_mtime > combinedtime
               for f in os.listdir(path) if f.endswith('.less')):
            print >>sys.stderr, ' * Recompiling %s' % entrypoint
            subprocess.call(['lessc', '-x', entrypoint, combined])

if __name__ == '__main__':
    app.debug = True
    app.run()

