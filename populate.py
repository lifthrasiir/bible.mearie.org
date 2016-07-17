# coding=utf-8
import json
import csv
import os
import re
import sys
import sqlite3
import bz2
import glob

def normalize(s):
    return u''.join(s.split()).upper()

def main(out='db/bible.db'):
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
            bookaliases[normalize(line['abbr_ko'])] = bookid, 'ko'
            bookaliases[normalize(line['title_ko'])] = bookid, 'ko'
            bookaliases[normalize(line['abbr_en'])] = bookid, 'en'
            bookaliases[normalize(line['title_en'])] = bookid, 'en'

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
            b, _ = bookaliases[normalize(b)]
            c = int(c)
            v = int(v)
            bcvs[b, c, v] = None
            bv = versionaliases[normalize(bv)]
            assert not any(u'\ue000' <= c <= u'\ue00f' for c in t)

            # \ue000..\ue001: italic
            # \ue002..\ue003: emphasis
            # \ue004..\ue005: strong emphasis
            # \ue006: placeholder for pending annotation
            t = t.replace(u'<i>', u'\ue000').replace(u'</i>', u'\ue001')
            if bv == u'kjav':
                t = t.replace(u'[', u'\ue002').replace(u']', u'\ue003')
                t = t.replace(u'{', u'\ue004').replace(u'}', u'\ue005')
            extra = []
            t = re.sub(ur'(?:\([\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+\))+',
                       lambda s: extra.append(s.group(0)) or u'\ue006', t)
            flags = 0
            text = u''
            markup = ''
            for s in t:
                ch = s[-1]
                if ch == u'\ue000': assert flags == 0; flags = 1
                elif ch == u'\ue001': assert flags == 1; flags = 0
                elif ch == u'\ue002': assert flags == 0; flags = 2
                elif ch == u'\ue003': assert flags == 2; flags = 0
                elif ch == u'\ue004': assert flags == 0; flags = 3
                elif ch == u'\ue005': assert flags == 3; flags = 0
                elif ch == u'\ue006': assert (flags & 128) == 0; flags |= 128
                else: text += ch; markup += chr(flags); flags &= 127
            if flags & 128: markup += chr(flags & 128)

            if markup.strip('\0'):
                meta = [markup] + [s.encode('utf-8') for s in extra]
                meta = buffer('\xff'.join(meta))
            else:
                assert not extra
                meta = None
            data.append((bv, (b, c, v), text, meta))

    data.sort()

    ordinal = 0
    index = {}
    minverse = {}
    maxverse = {}
    for b, c, v in sorted(bcvs.keys()):
        idx = index.get(b, 0)
        bcvs[b, c, v] = idx, ordinal
        if (b, c) not in minverse or minverse[b, c] > v: minverse[b, c] = v
        if (b, c) not in maxverse or maxverse[b, c] < v: maxverse[b, c] = v
        ordinal += 1
        index[b] = idx + 1
    verses = sorted((b, c, v, i, o) for (b,c,v), (i,o) in bcvs.items())
    data = sorted((bv, bcvs[bcv][1], text, meta) for bv, bcv, text, meta in data)

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

    path = 'data/daily.json'
    topics = []
    with open(path, 'rb') as f:
        print >>sys.stderr, 'reading %s' % path
        dailydata = json.load(f)
    for code, ranges in sorted(dailydata.items()):
        ordranges = []
        while ranges:
            book, _ = bookaliases[normalize(ranges[0])]
            if len(ranges) > 3 and isinstance(ranges[3], (int,long)):
                chapter1 = ranges[1]
                verse1 = ranges[2]
                chapter2 = ranges[3]
                verse2 = ranges[4]
                ranges = ranges[5:]
            else:
                chapter1 = ranges[1]
                verse1 = minverse[book, chapter1]
                chapter2 = ranges[2]
                verse2 = maxverse[book, chapter2]
                ranges = ranges[3:]
            _, ordinal1 = bcvs[book, chapter1, verse1]
            _, ordinal2 = bcvs[book, chapter2, verse2]
            ordranges.append((ordinal1, ordinal2))
        ordranges.sort()
        for i in xrange(len(ordranges)-2, -1, -1):
            assert ordranges[i][1] < ordranges[i+1][0]
            if ordranges[i][1] + 1 == ordranges[i+1][0]:
                ordranges[i] = (ordranges[i][0], ordranges[i+1][1])
                ordranges[i+1] = None
        for ordinal1, ordinal2 in filter(None, ordranges):
            topics.append(('daily', code, ordinal1, ordinal2))

    print >>sys.stderr, 'committing...'
    try: os.makedirs(os.path.dirname(out))
    except Exception: pass
    conn = sqlite3.connect(out)
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
            lang text,
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
            meta blob,
            primary key (version,ordinal));
        create table if not exists topics(
            kind text not null,
            code text not null,
            ordinal1 integer not null references verses(ordinal),
            ordinal2 integer not null references verses(ordinal),
            check (ordinal1 <= ordinal2),
            primary key (kind,code,ordinal1,ordinal2));
    ''')
    conn.executemany('insert into versions(version,abbr,lang,blessed,year,copyright,title_ko,title_en,maxgap) values(?,?,?,?,?,?,?,?,?);', versions)
    conn.executemany('insert into versionaliases(alias,version) values(?,?);', versionaliases.items())
    conn.executemany('insert into books(book,code,abbr_ko,title_ko,abbr_en,title_en) values(?,?,?,?,?,?);', books)
    conn.executemany('insert into bookaliases(alias,book,lang) values(?,?,?);', [(a,b,l) for a,(b,l) in bookaliases.items()])
    conn.executemany('insert into verses(book,chapter,verse,"index",ordinal) values(?,?,?,?,?);', verses)
    conn.executemany('insert into data(version,ordinal,"text",meta) values(?,?,?,?);', data)
    conn.executemany('insert into topics(kind,code,ordinal1,ordinal2) values(?,?,?,?);', topics)
    conn.commit()

if __name__ == '__main__':
    main(*sys.argv[1:2])

