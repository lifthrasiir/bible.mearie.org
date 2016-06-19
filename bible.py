# coding=utf-8
from flask import Flask, g, render_template, current_app, request, redirect, abort, url_for
from jinja2.utils import Markup
from werkzeug.routing import BaseConverter, ValidationError
from werkzeug.datastructures import MultiDict
from contextlib import contextmanager
from collections import namedtuple, OrderedDict
import sys
import re
import sqlite3
import urllib
import datetime
import bisect

sqlite3.register_converter('book', int)

app = Flask(__name__, static_folder='res', template_folder='tmpl')

@app.template_filter('classes')
def filter_classes(v):
    if not v: return u''
    return Markup(u' class="%s"') % u' '.join(v)

@app.template_filter('book')
def filter_book(v):
    return mappings.books[v]

@app.template_filter('htmltext')
def filter_htmltext(s, markup=None, keywords=None):
    if not s: return u''
    slower = s.lower()

    if markup is not None:
        markup = map(ord, markup)
    else:
        markup = [0] * len(s)

    kwmark = [None] * len(s)

    # flags:
    # 1 -- Capitalized
    # 2 -- UPPERCASED
    # 128 -- italicized (artificial text in KJV)

    # add pseudo keyword marks for query highlighting
    # marks are added in reverse, so the earlier keyword overwrites others.
    for k, keyword in list(enumerate(keywords or ()))[::-1]:
        keyword = keyword.lower()
        pos = -1
        while True:
            pos = slower.find(keyword, pos+1)
            if pos < 0: break
            for i in xrange(pos, pos+len(keyword)):
                kwmark[i] = k

    ss = []
    cur = []
    prevflags = 0
    prevmark = None
    for ch, flags, mark in zip(s, markup, kwmark) + [(u'', None, None)]:
        if flags is None or (flags, mark) != (prevflags, prevmark):
            ss.append(Markup().join(cur))
            cur = []

            closing = []
            opening = []

            flags = flags or 0
            changed = (prevflags ^ flags)
            cascade = False
            if cascade or mark != prevmark:
                if prevmark is not None: closing.append(Markup('</mark>'))
                if mark is not None: opening.append(Markup('<mark class="keyword%d">' % mark))
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
            prevmark = mark
            ss.extend(closing[::-1])
            ss.extend(opening)

        cur.append(ch)

    return Markup().join(ss)

class Entry(sqlite3.Row):
    def __init__(self, *args, **kwargs):
        sqlite3.Row.__init__(self, *args, **kwargs)
        self._primary_field = None

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def set_primary(self, name):
        assert name in self.keys()
        self._primary_field = name
        return self

    def __unicode__(self):
        if self._primary_field:
            return unicode(self[self._primary_field])
        else:
            return sqlite3.Row.__unicode__(self)

    def __str__(self):
        if self._primary_field:
            return str(self[self._primary_field])
        else:
            return sqlite3.Row.__str__(self)

@contextmanager
def database():
    db = sqlite3.connect('db/bible.db', detect_types=sqlite3.PARSE_COLNAMES)
    db.row_factory = Entry
    try:
        yield db
    finally:
        db.close()

# a universal cache for immutable data
class Mappings(object):
    def __init__(self):
        self.reload()

    def normalize(self, s):
        if not isinstance(s, (str, unicode)): s = str(s)
        return u''.join(s.split()).upper()

    def reload(self):
        with database() as db:
            self.books = []
            self.bookaliases = {}
            self.versions = {}
            self.versionaliases = {}
            self.blessedversions = {}

            # book: (minchapter, maxchapter)
            self.chapterranges = {}
            # (book,verse): (minverse, maxverse, deltaindex, deltaordinal)
            self.verseranges = {}
            # lexicographical_code: [(minordinal, maxordinal), ...]
            dailyranges = {}

            for row in db.execute('select * from books order by book;'):
                assert len(self.books) == row['book']
                row.set_primary('code')
                self.books.append(row)
                self.bookaliases[row['book']] = row
            for row in db.execute('select * from bookaliases;'):
                self.bookaliases[row['alias']] = self.books[row['book']], row['lang']
            for row in db.execute('select * from versions;'):
                row.set_primary('version')
                self.versions[row['version']] = row
                self.versionaliases[self.normalize(row['version'])] = row
                if row['blessed']:
                    self.blessedversions[row['lang']] = row
            for row in db.execute('select * from versionaliases;'):
                self.versionaliases[row['alias']] = self.versions[row['version']]

            for row in db.execute('''select book,
                                            min(chapter) as minchapter,
                                            max(chapter) as maxchapter
                                     from verses group by book;'''):
                self.chapterranges[row['book']] = \
                        (row['minchapter'], row['maxchapter'])
            for row in db.execute('''select book, chapter,
                                            min(verse) as minverse,
                                            max(verse) as maxverse,
                                            min("index") as minindex,
                                            max("index") as maxindex,
                                            min(ordinal) as minordinal,
                                            max(ordinal) as maxordinal
                                     from verses group by book, chapter;'''):
                assert (row['maxverse'] - row['minverse'] ==
                        row['maxindex'] - row['minindex'] ==
                        row['maxordinal'] - row['minordinal'])
                self.verseranges[row['book'], row['chapter']] = \
                        (row['minverse'], row['maxverse'],
                         row['minindex'] - row['minverse'],
                         row['minordinal'] - row['minverse'])
            for row in db.execute('''select code,
                                            v1.book as book1, v1.chapter as chapter1, v1.verse as verse1,
                                            v2.book as book2, v2.chapter as chapter2, v2.verse as verse2
                                     from topics
                                          inner join verses v1 on v1.ordinal = ordinal1
                                          inner join verses v2 on v2.ordinal = ordinal2
                                     where kind = ?;''', ('daily',)):
                bcv1 = (row['book1'], row['chapter1'], row['verse1'])
                bcv2 = (row['book2'], row['chapter2'], row['verse2'])
                dailyranges.setdefault(row['code'], []).append((bcv1, bcv2))

            for ranges in dailyranges.values(): ranges.sort()
            self.dailyranges = sorted(dailyranges.items())

        # TODO
        self.DEFAULT_VER = self.blessedversions['ko']['version']
        self.DEFAULT_VER_PER_LANG = {
            'ko': self.blessedversions['ko']['version'],
            'en': self.blessedversions['en']['version'],
        }

    def find_book_by_alias(self, alias):
        return self.bookaliases[self.normalize(alias)][0]

    def find_book_and_lang_by_alias(self, alias):
        return self.bookaliases[self.normalize(alias)]

    def find_version_by_alias(self, alias):
        return self.versionaliases[self.normalize(alias)]

    def get_recent_daily(self, code):
        # XXX a hack to locate the entry next to the today's entry
        index = bisect.bisect_right(self.dailyranges, (code + unichr(sys.maxunicode),))
        assert index <= 0 or self.dailyranges[index-1][0] <= code
        assert index >= len(self.dailyranges) or self.dailyranges[index][0] > code
        return Daily(index-1)

    def to_ordinal(self, (b,c,v)):
        try:
            minord = self.minordinals[b,c]
            maxord = self.maxordinals[b,c]
        except KeyError:
            raise ValueError('invalid book-chapter-verse pair')
        ord = minord + (v - 1)
        if not (minord <= ord <= maxord):
            raise ValueError('invalid book-chapter-verse pair')
        return ord

mappings = Mappings()
@app.context_processor
def inject_mappings():
    return {
        'debug': app.debug,
        'mappings': mappings,
        'build_query_suffix': build_query_suffix,
    }

_triple = namedtuple('triple', 'book chapter verse index ordinal')
class triple(_triple):
    def __new__(cls, book, chapter, verse):
        try:
            minchapter, maxchapter = mappings.chapterranges[book]
        except KeyError:
            raise ValueError('invalid book')
        if chapter == '$': chapter = maxchapter
        elif chapter <= 0: chapter = minchapter
        try:
            minverse, maxverse, deltaindex, deltaordinal = mappings.verseranges[book, chapter]
        except KeyError:
            raise ValueError('invalid chapter')
        if verse == '$': verse = maxverse
        elif verse <= 0: verse = minverse
        if not (minverse <= verse <= maxverse):
            raise ValueError('invalid verse')
        index = deltaindex + verse
        ordinal = deltaordinal + verse
        return _triple.__new__(cls, book, chapter, verse, index, ordinal)

    @property
    def book_and_chapter(self):
        return (self.book, self.chapter)

    @property
    def min_verse_in_chapter(self):
        minverse, maxverse, deltaindex, deltaordinal = mappings.verseranges[self.book, self.chapter]
        return minverse

    @property
    def max_verse_in_chapter(self):
        minverse, maxverse, deltaindex, deltaordinal = mappings.verseranges[self.book, self.chapter]
        return maxverse

class Daily(object):
    def __init__(self, index):
        code, ranges = mappings.dailyranges[index]
        self.index = index
        self.code = code
        self.ranges = [(triple(*bcv1), triple(*bcv2)) for bcv1, bcv2 in ranges]
        self.month, self.day = map(int, code.split('-', 1))

    @property
    def start(self):
        return self.ranges[0][0]

    @property
    def end(self):
        return self.ranges[-1][1]

    @property
    def num_verses(self):
        return sum(e.ordinal - s.ordinal + 1 for s, e in self.ranges)

    @property
    def prev(self):
        return Daily((self.index - 1) % len(mappings.dailyranges))

    @property
    def next(self):
        return Daily((self.index + 1) % len(mappings.dailyranges))


class Normalizable(namedtuple('Normalizable', 'before after')):
    def __str__(self): return str(self.after)
    def __unicode__(self): return unicode(self.after)
    def __getattr__(self, name): return getattr(self.after, name)

sqlite3.register_adapter(Entry, str)
sqlite3.register_adapter(Normalizable, str)

class BookConverter(BaseConverter):
    def to_python(self, value):
        try:
            return Normalizable(value, mappings.find_book_by_alias(value))
        except KeyError:
            raise ValidationError()

    def to_url(self, value):
        return str(value)

class IntOrEndConverter(BaseConverter):
    regex = r'(?:\d+|\$)'
    num_convert = int

    def to_python(self, value):
        if value != '$':
            try: value = int(value)
            except ValueError: raise ValidationError
        return value

    def to_url(self, value):
        if value != '$':
            value = str(int(value))
        return value

app.url_map.converters['book'] = BookConverter
app.url_map.converters['int_or_end'] = IntOrEndConverter

def build_query_suffix(**repl):
    normalized_version = str(g.version1) + (','+str(g.version2) if g.version2 else '')
    normalized_cursor = str(g.cursor) if g.cursor is not None else ''

    newquery = MultiDict(request.args)

    if normalized_version and normalized_version != mappings.DEFAULT_VER:
        newquery['v'] = normalized_version
    else:
        newquery.poplist('v')
    if normalized_cursor:
        newquery['c'] = normalized_cursor
    else:
        newquery.poplist('c')

    kvs = [(k, v.encode('utf-8')) for k, v in newquery.items(multi=True) if k not in repl]
    kvs += [(k, unicode(v).encode('utf-8')) for k, v in repl.items() if v is not None]
    newquery = urllib.urlencode(kvs)
    if newquery:
        return '?' + newquery
    else:
        return ''

def normalize_url(self, **kwargs):
    # common parameter `v`: version(s)
    # v=<v1> or v=<v1>,<v2>
    orig_version = request.args.get('v', '')
    v1, _, v2 = orig_version.partition(',')
    try:
        g.version1 = mappings.find_version_by_alias(v1)
    except Exception:
        g.version1 = mappings.versions[mappings.DEFAULT_VER]
    try:
        g.version2 = mappings.find_version_by_alias(v2)
        if g.version1 == g.version2: g.version2 = None
    except Exception:
        g.version2 = None
    normalized_version = str(g.version1) + (','+str(g.version2) if g.version2 else '')
    if normalized_version == mappings.DEFAULT_VER: normalized_version = ''

    # common parameter `c`: cursor
    # c=<after> or c=<~before>
    orig_cursor = request.args.get('c', '')
    try:
        g.cursor = int(orig_cursor) if len(orig_cursor) <= 6 else None
    except Exception:
        g.cursor = None
    normalized_cursor = str(g.cursor) if g.cursor is not None else ''

    need_redirect = (orig_version != normalized_version or \
                     orig_cursor != normalized_cursor)
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

def render_verses(tmpl, (prevc, verses, nextc), **kwargs):
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
                           sections=tbodys, prevc=prevc, nextc=nextc, **kwargs)

def execute_verses_query(db, cursor=None, where='1', args=(), count=100):
    inverted = False
    if cursor is not None:
        if cursor >= 0:
            where += ' and v.ordinal >= ?'
            args += (cursor,)
        else:
            where += ' and v.ordinal <= ?'
            args += (~cursor,)
            inverted = True

    limit = ''
    if count:
        limit = ' limit ?'
        args += (count,)

    if g.version2:
        verses = db.execute('''
            select v.book as "book [book]", v.*, d.text as text, d.markup as markup,
                        d2.text as text2, d2.markup as markup2
            from verses v left outer join data d on d.version=? and v.ordinal=d.ordinal
                          left outer join data d2 on d2.version=? and v.ordinal=d2.ordinal
            where ''' + where + '''
            order by ordinal ''' + ('desc' if inverted else 'asc') + limit + ''';
        ''', (g.version1, g.version2) + args)
    else:
        verses = db.execute('''
            select v.book as "book [book]", v.*, d.text as text, d.markup as markup
            from verses v left outer join data d on d.version=? and v.ordinal=d.ordinal
            where ''' + where + '''
            order by ordinal ''' + ('desc' if inverted else 'asc') + limit + ''';
        ''', (g.version1,) + args)

    verses = verses.fetchall()
    if inverted: verses.reverse()
    return verses

def adjust_for_cursor(verses, cursor, count):
    excess = count and len(verses) > count
    if cursor is None:
        nextc = verses.pop().ordinal if excess else None # pop first
        prevc = None
    elif cursor >= 0:
        nextc = verses.pop().ordinal if excess else None # pop first
        prevc = ~(verses[0].ordinal - 1) if verses and verses[0].ordinal > 0 else None
    else:
        prevc = ~verses.pop(0).ordinal if excess else None # pop first
        nextc = verses[-1].ordinal + 1 if verses else None
    return prevc, verses, nextc

def get_verses_unbounded(db, where='1', args=(), count=100, **kwargs):
    verses = execute_verses_query(db, g.cursor, where=where, args=args,
            count=count+1 if count else None, **kwargs)
    return adjust_for_cursor(verses, g.cursor, count)

def get_verses_bounded(db, minordinal, maxordinal, where='1', args=(), count=100, **kwargs):
    verses = execute_verses_query(db, g.cursor, where=where, args=args,
            count=count+2 if count else None, **kwargs)

    smaller = []
    inrange = []
    larger = []
    for row in verses:
        if row['ordinal'] < minordinal:
            smaller.append(row)
        elif row['ordinal'] > maxordinal:
            larger.append(row)
        else:
            inrange.append(row)

    # cursor code expects at most `count+1` verses.
    # +2 adjustment was only to account for a non-empty `smaller`, so we no longer need that.
    del inrange[count+1:]

    # if we have a non-empty `larger`, `inrange` should be the final page.
    if not larger:
        prevc, inrange, nextc = adjust_for_cursor(inrange, g.cursor, count)
        if prevc and ~prevc < minordinal: prevc = None
    else:
        prevc = ~(inrange[0].ordinal - 1) if inrange and inrange[0].ordinal > minordinal else None
        nextc = None

    return smaller[-1] if smaller else None, (prevc, inrange, nextc), larger[0] if larger else None


@app.route('/')
def index():
    today = datetime.date.today()
    daily = mappings.get_recent_daily('%02d-%02d' % (today.month, today.day))
    return render_template('index.html', query=u'', books=mappings.books, daily=daily)

@app.route('/+/about')
def about():
    return render_template('about.html', query=u'')

@app.route('/+/daily/')
@app.route('/+/daily/<code>')
def daily(code=None):
    if code is None:
        today = datetime.date.today()
        actualcode = '%02d-%02d' % (today.month, today.day)
    else:
        if len(code) == 5 and code[:2].isdigit() and code[2] == '-' and code[3:].isdigit():
            actualcode = code
        else:
            abort(404)

    normalize_url('.daily', code=actualcode)

    daily = mappings.get_recent_daily(actualcode)
    if daily.code != code:
        return redirect(url_for('.daily', code=daily.code))
    with database() as db:
        where = ' and '.join(['(v.ordinal between ? and ?)'] * len(daily.ranges))
        args = tuple(bcv.ordinal for start_end in daily.ranges for bcv in start_end)
        verses_and_cursors = get_verses_unbounded(db, where, args, count=None)

    query = u'' # XXX
    return render_verses('daily.html', verses_and_cursors, query=query, daily=daily)

@app.route('/+/daily/list')
def daily_list():
    today = datetime.date.today()
    daily = mappings.get_recent_daily('%02d-%02d' % (today.month, today.day))
    dailylist = map(Daily, xrange(len(mappings.dailyranges)))
    return render_template('daily_list.html', query=u'', daily=daily, dailylist=dailylist)

@app.route('/search')
def search():
    query = request.args['q'].strip()
    if not query: return redirect('/')

    normalize_url('.search')

    # search syntax:
    # - lexemes are primarily separated (and ordered) by non-letter characters.
    # - quotes can be used to escape whitespaces. no intra-quotes are accepted.
    # - any lexeme (including quoted one) can be prefixed by `tag:` to clarify meaning.
    # - there can only be one occurrence of chapter-verse range spec.
    #   the spec has its own syntax and is not governed by the ordinary separator.
    #   the range spec does not include the ordinary number, so that "1 John" etc. can be parsed.
    # - a series of untagged unquoted lexemes is concatenated *again* and checked for known tokens.
    # - any unrecognized token becomes a search keyword.
    #
    # example:
    # "John 3:16" -> book:John, range:3:16
    # "John 3 - 4 (KJV/개역)" -> book:John, range:3-4, version:KJV, version:개역
    # "John b:3 - 4 (KJV/개역)" -> book:John, book:3, keyword:4, version:KJV, version:개역
    # "2 1 John" -> range:2, book:1John
    # "1 John 2 John" -> book:1John, book:2John (probably an error)
    # "요한 계시록 어린양" -> book:Rev, keyword:어린양
    # "요한 keyword:어린양 계시록" -> keyword:요한, keyword:어린양, keyword:계시록
    # "'alpha and omega' niv" -> keyword:"alpha and omega", version:NIV

    TAGS = {
        u'v': u'version', u'ver': u'version', u'version': u'version',
        u'q': u'keyword', u'keyword': u'keyword',
        u'b': u'book', u'book': u'book',
        # the pseudo-tag "range" is used for chapter and verse ranges
    }

    # parse the query into a series of tagged and untagged lexeme
    lexemes = []
    for m in re.findall(ur'(?ui)'
                        # chapter-verse range spec (1:2, 1:2-3:4, 1:2 ~ 4 etc.)
                        ur'(\d+\s*:\s*\d+)(?:\s*[-~]\s*(\d+(?:\s*:\s*\d+)?))?|'
                        # chapter-only range spec (1-2, 1 ~ 2 etc.)
                        # the single number is parsed later
                        ur'(\d+)\s*[-~]\s*(\d+)|'
                        # lexeme with optional tag (foo, v:asdf, "a b c", book:'x y z' etc.)
                        # a row of letters and digits does not mix (e.g. 창15 -> 창, 15)
                        ur'(?:(' + u'|'.join(map(re.escape, TAGS)) + ur'):)?'
                            ur'(?:"([^"]*)"|\'([^\']*)\'|((?:[^\W\d]|[\-\'])+|\d+))', query):
        if m[0]:
            chap1, _, verse1 = m[0].partition(u':')
            chap1 = int(chap1)
            verse1 = int(verse1)
            if m[1]:
                chap2, _, verse2 = m[1].rpartition(u':')
                chap2 = int(chap2 or chap1)
                verse2 = int(verse2)
            else:
                chap2 = verse2 = None
            lexemes.append(('range', (chap1, chap2, verse1, verse2)))
        elif m[2]:
            chap1 = int(m[2])
            if m[3] is not None:
                chap2 = int(m[3])
            else:
                chap2 = None
            lexemes.append(('range', (chap1, chap2, None, None)))
        elif m[4]:
            lexemes.append((TAGS[m[4]], m[5] or m[6] or m[7]))
        elif m[5] or m[6]:
            # quoted untagged lexemes are always keywords
            lexemes.append(('keyword', m[5] or m[6]))
        else:
            # unquoted untagged lexemes are resolved later
            if not (lexemes and lexemes[-1][0] is None):
                lexemes.append((None, []))
            lexemes[-1][1].append(m[7])

    # resolve remaining unquoted untagged lexemes
    tokens = []
    for lexeme in lexemes:
        if lexeme[0] is None:
            unquoted = lexeme[1]
            start = 0
            while start < len(unquoted):
                s = u''
                # avoid quadratic complexity, no token is more than 5 words long
                for i in xrange(start, min(start+5, len(unquoted))):
                    s += unquoted[i]
                    try:
                        book, lang = mappings.find_book_and_lang_by_alias(s)
                        tokens.append(('book', s))
                        start = i + 1
                        break
                    except KeyError:
                        pass
                    try:
                        version = mappings.find_version_by_alias(s)
                        if version.blessed: # TODO temporary
                            tokens.append(('version',s))
                            start = i + 1
                            break
                    except KeyError:
                        pass
                else:
                    if unquoted[start].isdigit():
                        tokens.append(('range', (int(unquoted[start]), None, None, None)))
                    else:
                        tokens.append(('keyword', unquoted[start]))
                    start += 1
        else:
            tokens.append(lexeme)

    # implied language is used to resolve versions when no other infos are available
    implied_lang = set()
    tagged = {}
    for tag, value in tokens:
        tagged.setdefault(tag, []).append(value)
        if tag == 'version':
            try:
                version = mappings.find_version_by_alias(s)
                implied_lang.add(version.lang)
            except KeyError:
                pass
        elif tag == 'book':
            try:
                book, lang = mappings.find_book_and_lang_by_alias(s)
                if lang: implied_lang.add(lang)
            except KeyError:
                pass
        elif tag == 'keyword':
            if all(u'가' <= c <= u'힣' for c in value):
                implied_lang.add('ko')
            elif all(not c.isalpha() or u'a' <= c <= 'z' or u'A' <= c <= u'Z' for c in value):
                implied_lang.add('en')

    if len(implied_lang) == 1:
        implied_lang, = list(implied_lang)
    else:
        implied_lang = None # unknown or ambiguous

    old_version = g.version1, g.version2
    if 'version' in tagged:
        versions = []
        seen = set()
        for s in tagged['version']:
            try:
                version = mappings.find_version_by_alias(s)
                if version.blessed: # TODO temporary
                    if version.version not in seen:
                        seen.add(version.version)
                        versions.append(version)
            except KeyError:
                pass

        g.version1 = versions[0] if len(versions) > 0 else None
        g.version2 = versions[1] if len(versions) > 1 else None
        # TODO version3 and later
    else:
        # if there is no other version hint but an implied lang, use it
        if not request.args.get('v') and implied_lang:
            g.version1 = mappings.versions[mappings.DEFAULT_VER_PER_LANG[implied_lang]]

    version_updated = (g.version1, g.version2) != old_version

    if 'book' in tagged:
        books = []
        for s in tagged['book']:
            try:
                book = mappings.find_book_by_alias(s)
                books.append(book)
            except KeyError:
                pass

        if books:
            book = books[0]
            # TODO 2 or more books

            if 'range' in tagged:
                # TODO check for len(tagged['range']) > 1
                chap1, chap2, verse1, verse2 = tagged['range'][0]
                if verse1:
                    if chap2:
                        assert verse2
                        url = url_for('.view_verses', book=book, chapter1=chap1, verse1=verse1,
                                                                 chapter2=chap2, verse2=verse2)
                    else:
                        url = url_for('.view_verse', book=book, chapter=chap1, verse=verse1)
                else:
                    if chap2:
                        url = url_for('.view_chapters', book=book, chapter1=chap1, chapter2=chap2)
                    else:
                        url = url_for('.view_chapter', book=book, chapter=chap1)
            else:
                url = url_for('.view_book', book=book)

            return redirect(url + build_query_suffix(q=None))

    keywords = tagged.get('keyword', [])
    if not keywords: return redirect('/')
    uniqwords = OrderedDict((w.lower(), w) for w in keywords) # zap duplicates

    # for reconstructed queries, we need to insert quotes as needed.
    # we also have to preserve cases while removing duplicates...
    keywords = uniqwords.keys()
    query = u' '.join(u'"%s"' % w if w.startswith("'") or
                                     any(not c.isalpha() and not c.isdigit() and
                                         c != '-' and c != "'" for c in w) else
                      u"'%s'" % w if w.startswith("'") else
                      w for w in uniqwords.values())

    # version parameter should be re-normalized
    if version_updated:
        return redirect(url_for('.search') + build_query_suffix(q=query))

    with database() as db:
        verses_and_cursors = get_verses_unbounded(db,
                ' and '.join(['d."text" like ?'] * len(keywords)),
                tuple('%%%s%%' % keyword for keyword in keywords))

    return render_verses('search.html', verses_and_cursors, query=query, keywords=keywords)

@app.route('/<book:book>/')
def view_book(book):
    normalize_url('.view_book', book=book)
    return redirect(url_for('.view_chapter', book=book, chapter=1) + build_query_suffix())

@app.route('/<book:book>/<int_or_end:chapter>')
def view_chapter(book, chapter):
    normalize_url('.view_chapter', book=book, chapter=chapter)
    try:
        start = triple(book.book, chapter, 0)
        end = triple(book.book, chapter, '$')
    except Exception:
        abort(404)

    with database() as db:
        prev, verses_and_cursors, next = get_verses_bounded(db, start.ordinal, end.ordinal,
                'v.ordinal between ? and ?', (start.ordinal-1, end.ordinal+1))

    query = u'%s %d' % (book.abbr_ko, start.chapter)
    return render_verses('chapters.html', verses_and_cursors, query=query, prev=prev, next=next,
                         book=book, chapter1=start.chapter, chapter2=end.chapter)

@app.route('/<book:book>/<int_or_end:chapter1>-<int_or_end:chapter2>')
def view_chapters(book, chapter1, chapter2):
    normalize_url('.view_chapters', book=book, chapter1=chapter1, chapter2=chapter2)
    try:
        start = triple(book.book, chapter1, 0)
        end = triple(book.book, chapter2, '$')
    except Exception:
        abort(404)
    if start.ordinal > end.ordinal:
        return redirect(url_for('.view_chapters', book=book, chapter1=chapter2, chapter2=chapter1))

    with database() as db:
        prev, verses_and_cursors, next = get_verses_bounded(db, start.ordinal, end.ordinal,
                'v.ordinal between ? and ?', (start.ordinal-1, end.ordinal+1))

    query = u'%s %d-%d' % (book.abbr_ko, start.chapter, end.chapter)
    return render_verses('chapters.html', verses_and_cursors, query=query, prev=prev, next=next,
                         book=book, chapter1=start.chapter, chapter2=end.chapter)

def do_view_verses(book, start, end, query):
    bcv1 = (start.book, start.chapter, start.verse)
    bcv2 = (end.book, end.chapter, end.verse)
    highlight = lambda b,c,v: bcv1 <= (b,c,v) <= bcv2

    with database() as db:
        verses_and_cursors = get_verses_unbounded(db, 'v.book=? and v."index" between ? and ?',
                (book.book, start.index-5, end.index+5))

    return render_verses('verses.html', verses_and_cursors, query=query, highlight=highlight,
                         book=book, chapter1=start.chapter, verse1=start.verse,
                         chapter2=end.chapter, verse2=end.verse)

@app.route('/<book:book>/<int_or_end:chapter>.<int_or_end:verse>')
def view_verse(book, chapter, verse):
    normalize_url('.view_verse', book=book, chapter=chapter, verse=verse)
    try:
        start = end = triple(book.book, chapter, verse)
    except Exception:
        abort(404)
    query = u'%s %d:%d' % (book.abbr_ko, start.chapter, start.verse)
    return do_view_verses(book, start, end, query)

@app.route('/<book:book>/<int_or_end:chapter1>.<int_or_end:verse1>-<int_or_end:chapter2>.<int_or_end:verse2>')
def view_verses(book, chapter1, verse1, chapter2, verse2):
    normalize_url('.view_verses', book=book, chapter1=chapter1, verse1=verse1,
                  chapter2=chapter2, verse2=verse2)
    try:
        start = triple(book.book, chapter1, verse1)
        end = triple(book.book, chapter2, verse2)
    except Exception:
        abort(404)
    if start.ordinal > end.ordinal:
        return redirect(url_for('.view_verses', book=book, chapter1=chapter2, verse1=verse2,
                                                           chapter2=chapter1, verse2=verse1))

    if chapter1 == chapter2:
        query = u'%s %d:%d-%d' % (book.abbr_ko, start.chapter, start.verse, end.verse)
    else:
        query = u'%s %d:%d-%d:%d' % (book.abbr_ko, start.chapter, start.verse,
                                     end.chapter, end.verse)
    return do_view_verses(book, start, end, query)

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
    app.run('0.0.0.0', int(sys.argv[1]) if len(sys.argv) > 1 else 5000)

