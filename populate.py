# coding=utf-8
import json
import csv
import sys
import sqlite3
import bz2
import glob

def normalize(s):
    return u''.join(s.split()).upper()

versions = []
versionaliases = {}
path = 'data/versions.json'
with open(path, 'rb') as f:
    print >>sys.stderr, 'reading %s' % path
    verdata = json.load(f)
for line in verdata['versions']:
    versions.append((line['id'], line['abbr'], line['lang'], int(line['blessed']),
                     line['year'], line['copyright'],
                     line['title'].get('ko'), line['title'].get('en')))
    versionaliases[normalize(line['abbr'])] = line['id']
for k, v in verdata['aliases'].items():
    versionaliases[normalize(k)] = v

books = []
bookaliases = {}
path = 'data/books.csv'
with open(path, 'rb') as f:
    print >>sys.stderr, 'reading %s' % path
    bookdata = csv.reader(f)
    keys = bookdata.next() # has a header
    for line in bookdata:
        line = dict(map(None, keys, [s.decode('utf-8') for s in line]))
        bookid = int(line['id'])
        books.append((bookid, line['code'],
                      line['abbr_ko'], line['title_ko'],
                      line['abbr_en'], line['title_en']))
        bookaliases[normalize(line['abbr_ko'])] = bookid
        bookaliases[normalize(line['title_ko'])] = bookid
        bookaliases[normalize(line['abbr_en'])] = bookid
        bookaliases[normalize(line['title_en'])] = bookid

bcvs = {}
data = []
for f in glob.glob('data/verses_*.txt.bz2'):
    i = 0
    for line in bz2.BZ2File(f, 'rb'):
        i += 1
        if i % 10000 == 0: print >>sys.stderr, 'reading %s: line %d' % (f, i)
        line = line.rstrip('\r\n').decode('utf-8')
        if not line: continue
        bv, b, c, v, t = line.split('\t')
        if bv not in versionaliases: continue
        b = bookaliases[normalize(b)]
        c = int(c)
        v = int(v)
        bcvs[b, c, v] = None
        bv = versionaliases[normalize(bv)]
        assert not any(u'\ue000' <= c <= u'\ue00f' for c in t)

        # \ue000..\ue001: italic
        # \ue002..\ue003: emphasis
        # \ue004..\ue005: strong emphasis
        t = t.replace(u'<i>', u'\ue000').replace(u'</i>', u'\ue001')
        if bv == u'kjav':
            t = t.replace(u'[', u'\ue002').replace(u']', u'\ue003')
            t = t.replace(u'{', u'\ue004').replace(u'}', u'\ue005')
        flags = 0
        text = u''; markup = ''
        for ch in t:
            if ch == u'\ue000': assert flags == 0; flags = 128
            elif ch == u'\ue001': assert flags == 128; flags = 0
            elif ch == u'\ue002': assert flags == 0; flags = 1
            elif ch == u'\ue003': assert flags == 1; flags = 0
            elif ch == u'\ue004': assert flags == 0; flags = 2
            elif ch == u'\ue005': assert flags == 2; flags = 0
            else: text += ch; markup += chr(flags)
        data.append((bv, (b, c, v), text, buffer(markup) if markup.strip('\0') else None))

data.sort()

ordinal = 0
index = {}
for b, c, v in sorted(bcvs.keys()):
    idx = index.get(b, 0)
    bcvs[b, c, v] = ordinal, idx
    ordinal += 1
    index[b] = idx + 1
verses = sorted((b, c, v, i, o) for (b,c,v), (o,i) in bcvs.items())
data = sorted((bv, bcvs[bcv][0], text, markup) for bv, bcv, text, markup in data)

# there are some gaps between consecutive verses in particular versions
# in terms of ordinals. so we fetch MAXGAP more verses for previous or
# next verses processing.
def append_maxgap(row):
    bv = row[0]
    ords = [ordinal for ibv, ordinal, _, _ in data if bv == ibv]
    assert ords == sorted(ords)
    if ords:
        maxgap = max(o2-o1 for o1, o2 in zip(ords, ords[1:]))
    else:
        maxgap = 0
    return row + (maxgap,)
versions = map(append_maxgap, versions)


print >>sys.stderr, 'committing...'
conn = sqlite3.connect('bible.db')
conn.executescript('''
    create table if not exists versions(
        version text not null primary key,
        abbr text not null unique,
        lang text not null,
        blessed integer not null,
        year integer,
        copyright text,
        title_ko text,
        title_en text,
        maxgap integer not null);
    create table if not exists versionaliases(
        alias text not null,
        version text not null references versions(version),
        primary key (alias,version));
    create table if not exists books(
        book integer not null primary key,
        code text not null unique,
        abbr_ko text not null unique,
        title_ko text not null,
        abbr_en text not null unique,
        title_en text not null);
    create table if not exists bookaliases(
        alias text not null,
        book integer not null references books(book),
        primary key (alias,book));
    create table if not exists verses(
        book integer not null references books(book),
        chapter integer not null,
        verse integer not null,
        "index" integer not null, -- w.r.t. book
        ordinal integer not null, -- w.r.t. whole bible
        primary key (ordinal),
        unique (book,"index"),
        unique (book,chapter,verse));
    create table if not exists data(
        version text not null references versions(version),
        ordinal integer not null references verses(ordinal),
        "text" text not null,
        markup blob,
        primary key (version,ordinal));
''')
conn.executemany('insert into versions(version,abbr,lang,blessed,year,copyright,title_ko,title_en,maxgap) values(?,?,?,?,?,?,?,?,?);', versions)
conn.executemany('insert into versionaliases(alias,version) values(?,?);', versionaliases.items())
conn.executemany('insert into books(book,code,abbr_ko,title_ko,abbr_en,title_en) values(?,?,?,?,?,?);', books)
conn.executemany('insert into bookaliases(alias,book) values(?,?);', bookaliases.items())
conn.executemany('insert into verses(book,chapter,verse,"index",ordinal) values(?,?,?,?,?);', verses)
conn.executemany('insert into data(version,ordinal,"text",markup) values(?,?,?,?);', data)
conn.commit()

