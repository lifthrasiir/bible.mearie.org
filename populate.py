# coding=utf-8
import sys
import sqlite3
import bz2
import glob

versions = {
    u'KJV': 'kjv', u'NASV': 'nasv', u'NIV': 'niv', u'NKJV': 'nkjv',
    u'NLT': 'nlt', u'NRSV': 'nrsv', u'NWT': 'nwt', u'개역': 'krv',
    u'개정': 'nkrv', u'공동': 'ctb', u'권위역': 'kav', u'표준': 'nksb',
    u'한킹': 'kkjv', u'현대어': 'tkv', u'현대인': 'klb', u'흠정역': 'kjav',
}
books = [
    u'창', u'출', u'레', u'민', u'신', u'수', u'삿', u'룻', u'삼상', u'삼하',
    u'왕상', u'왕하', u'대상', u'대하', u'스', u'느', u'에', u'욥', u'시',
    u'잠', u'전', u'아', u'사', u'렘', u'애', u'겔', u'단', u'호', u'욜', u'암',
    u'옵', u'욘', u'미', u'나', u'합', u'습', u'학', u'슥', u'말',
    u'마', u'막', u'눅', u'요', u'행', u'롬', u'고전', u'고후', u'갈', u'엡',
    u'빌', u'골', u'살전', u'살후', u'딤전', u'딤후', u'딛', u'몬', u'히',
    u'약', u'벧전', u'벧후', u'요일', u'요이', u'요삼', u'유', u'계',
]

bcvs = {}
data = []
for f in glob.glob('data/verses_*.txt.bz2'):
    i = 0
    for line in bz2.BZ2File(f, 'rb'):
        i += 1
        if i % 10000 == 0: print >>sys.stderr, '%s: line %d' % (f, i)
        line = line.rstrip('\r\n').decode('utf-8')
        if not line: continue
        bv, b, c, v, t = line.split('\t')
        if bv not in versions: continue
        b = books.index(b)
        c = int(c)
        v = int(v)
        bcvs[b, c, v] = None
        try: bv = versions[bv]
        except KeyError: continue
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



conn = sqlite3.connect('bible.db')
conn.executescript('''
    create table if not exists verses(
        book integer not null,
        chapter integer not null,
        verse integer not null,
        "index" integer not null, -- w.r.t. book
        ordinal integer not null, -- w.r.t. whole bible
        primary key (ordinal),
        unique (book,"index"),
        unique (book,chapter,verse));
    create table if not exists data(
        version text not null,
        ordinal integer not null references verses(ordinal),
        "text" text not null,
        markup blob,
        primary key (version,ordinal));
''')
conn.executemany('insert into verses(book,chapter,verse,"index",ordinal) values(?,?,?,?,?);', verses)
conn.executemany('insert into data(version,ordinal,"text",markup) values(?,?,?,?);', data)
conn.commit()

