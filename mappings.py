# coding=utf-8

class Entry(object):
    def __init__(self, code, **kwargs):
        self.code = code
        self.others = set(kwargs.pop('others', ()))
        self.kwargs = kwargs

    def __getattr__(self, name):
        try:
            return self.kwargs[name]
        except KeyError:
            raise AttributeError(name)

    def __cmp__(self, other):
        return cmp(self.code, other.code)

    def __repr__(self):
        items = self.kwargs.items()
        if self.others: items.append(('others', self.others))
        items.sort(key=lambda (k,v): (k=='others', k))
        return '%s(%r%s)' % (self.__class__.__name__, self.code,
                             ''.join(', %s=%r' % (k,v) for k,v in items))

    def __str__(self):
        return self.code

    def all_values(self):
        return self.others.union(v for k,v in self.kwargs.items() if not k.startswith('_'))

class Entries(list):
    def __init__(self, *args):
        super(Entries, self).__init__(args)
        self.invalidate()

    def invalidate(self):
        self._code2entry = self._value2entry = None

    def _refresh(self):
        code2entry = {}
        value2entry = {}
        indices = {}
        for i, entry in enumerate(self):
            code2entry[entry.code.strip().lower()] = entry
            indices[entry.code] = i
            for val in entry.all_values():
                value2entry[u''.join(val.split()).lower()] = entry
        self._code2entry = code2entry
        self._value2entry = value2entry
        self._indices = indices

    def _refresh_if_needed(self):
        if self._code2entry is None or self._value2entry is None:
            self._refresh()

    @property
    def indices(self):
        self._refresh_if_needed()
        return self._indices

    def from_code(self, code):
        self._refresh_if_needed()
        return self._code2entry[code.strip().lower()]

    def from_value(self, value):
        self._refresh_if_needed()
        return self._value2entry[u''.join(value.split()).lower()]

    def from_any(self, s):
        self._refresh_if_needed()
        s = u''.join(s.split()).lower()
        try:
            return self._code2entry[s]
        except KeyError:
            return self._value2entry[s]

    def all_values(self):
        return set().union(*[entry.all_values() for entry in self])

    def all_codes(self):
        return set(entry.code for entry in self)

# Almost all abbreviations for Korean translations are provisional.
versions = Entries(
    Entry('kjv',  _lang='en', _year=1611, _blessed=True,
                  _copyright=u'퍼블릭 도메인; 영국 내에서는 출판 허가가 필요',
                  en=u'KJV', eng=u'King James Version'),
    Entry('nasv', _lang='en', _year=1970, _blessed=False,
                  _copyright=u'Lockman Foundation',
                  en=u'NASV', eng=u'New American Standard Version'),
    Entry('niv',  _lang='en', _year=1978, _blessed=False,
                  _copyright=u'International Bible Society',
                  en=u'NIV', eng=u'New International Version'),
    Entry('nkjv', _lang='en', _year=1983, _blessed=False,
                  _copyright=u'Thomas Nelson, Inc.',
                  en=u'NKJV', eng=u'New King James Version'),
    Entry('nlt',  _lang='en', _year=1996, _blessed=False,
                  _copyright=u'Tyndale House Publisher',
                  en=u'NLT', eng=u'New Living Translation'),
    Entry('nrsv', _lang='en', _year=1989, _blessed=False,
                  _copyright=u'National Council of Churches of Christ',
                  en=u'NRSV', eng=u'New Revised Version'),
    Entry('nwt',  _lang='en', _year=1984, _blessed=False,
                  _copyright=u'Watchtower Society',
                  en=u'NWT', eng=u'New World Translation'),
    Entry('krv',  _lang='ko', _year=1961, _blessed=False,
                  _copyright=u'대한성서공회',
                  ko=u'개역', kor=u'개역성경', eng=u'Korean Revised Version'),
    Entry('nkrv', _lang='ko', _year=1998, _blessed=False,
                  _copyright=u'대한성서공회',
                  ko=u'개정', kor=u'개역 개정판', eng=u'New Revised Korean Version',
                  _others=[u'개역개정']),
    Entry('ctb',  _lang='ko', _year=1977, _blessed=False,
                  _copyright=u'대한성서공회',
                  ko=u'공동', kor=u'공동번역', eng=u'Common Translation Bible'),
    Entry('kav',  _lang='ko', _year=2001, _blessed=False,
                  _copyright=u'퍼블릭 도메인 (안티오크 하우스)',
                  ko=u'권위역', kor=u'권위역', eng=u'Korean Authorized Version'),
    Entry('nksb', _lang='ko', _year=1993, _blessed=False,
                  _copyright=u'대한성서공회',
                  ko=u'표준', kor=u'표준새번역', eng=u'New Korean Standard Bible'),
    Entry('kkjv', _lang='ko', _year=1994, _blessed=False,
                  _copyright=u'말씀보존학회',
                  ko=u'한킹', kor=u'한글 킹제임스 성경', eng=u'Korean King James Version'),
    Entry('tkv',  _lang='ko', _year=1991, _blessed=False,
                  _copyright=u'성경원',
                  ko=u'현대어', kor=u'현대어성경', eng=u'Today\'s Korean Version'),
    Entry('klb',  _lang='ko', _year=1985, _blessed=False,
                  _copyright=u'생명의말씀사',
                  ko=u'현대인', kor=u'현대인의성경', eng=u'Korean Living Bible'),
    Entry('kjav', _lang='ko', _year=2011, _blessed=True,
                  _copyright=u'그리스도 예수안에',
                  ko=u'흠정역', kor=u'킹제임스 흠정역 (5판)',
                                eng=u'Korean Authorized King James Version',
                  others=[u'흠정']),
)

DEFAULT_VER = 'kjav'

# codes derived from common abbreviations for books of the Bible, MLA/Chicago style
# limited to 5 characters including volume number, prefers a longer abbreviation if possible
books = Entries(
    Entry('Gen',   ko=u'창',   kor=u'창세기',         en='Gen',   eng='Genesis'),
    Entry('Exod',  ko=u'출',   kor=u'출애굽기',       en='Exod',  eng='Exodus'),
    Entry('Lev',   ko=u'레',   kor=u'레위기',         en='Lev',   eng='Leviticus'),
    Entry('Num',   ko=u'민',   kor=u'민수기',         en='Num',   eng='Numbers'),
    Entry('Deut',  ko=u'신',   kor=u'신명기',         en='Deut',  eng='Deuteronomy'),
    Entry('Josh',  ko=u'수',   kor=u'여호수아',       en='Josh',  eng='Joshua'),
    Entry('Judg',  ko=u'삿',   kor=u'사사기',         en='Judg',  eng='Judges'),
    Entry('Ruth',  ko=u'룻',   kor=u'룻기',           en='Ruth',  eng='Ruth'),
    Entry('1Sam',  ko=u'삼상', kor=u'사무엘상',       en='1Sam',  eng='1 Samuel'),
    Entry('2Sam',  ko=u'삼하', kor=u'사무엘하',       en='2Sam',  eng='2 Samuel'),
    Entry('1Kgs',  ko=u'왕상', kor=u'열왕기상',       en='1Kgs',  eng='1 Kings'),
    Entry('2Kgs',  ko=u'왕하', kor=u'열왕기하',       en='2Kgs',  eng='2 Kings'),
    Entry('1Chr',  ko=u'대상', kor=u'역대상',         en='1Chr',  eng='1 Chronicles'),
    Entry('2Chr',  ko=u'대하', kor=u'역대하',         en='2Chr',  eng='2 Chronicles'),
    Entry('Ezra',  ko=u'스',   kor=u'에스라',         en='Ezra',  eng='Ezra'),
    Entry('Neh',   ko=u'느',   kor=u'느헤미야',       en='Neh',   eng='Nehemiah'),
    Entry('Esth',  ko=u'에',   kor=u'에스더',         en='Esth',  eng='Esther'),
    Entry('Job',   ko=u'욥',   kor=u'욥기',           en='Job',   eng='Job'),
    Entry('Ps',    ko=u'시',   kor=u'시편',           en='Ps',    eng='Psalms'),
    Entry('Prov',  ko=u'잠',   kor=u'잠언',           en='Prov',  eng='Proverbs'),
    Entry('Eccl',  ko=u'전',   kor=u'전도서',         en='Eccl',  eng='Ecclesiastes'),
    Entry('Song',  ko=u'아',   kor=u'아가',           en='Song',  eng='Song of Songs'),
    Entry('Isa',   ko=u'사',   kor=u'이사야',         en='Isa',   eng='Isaiah'),
    Entry('Jer',   ko=u'렘',   kor=u'예레미야',       en='Jer',   eng='Jeremiah'),
    Entry('Lam',   ko=u'애',   kor=u'예레미야애가',   en='Lam',   eng='Lamentations'),
    Entry('Ezek',  ko=u'겔',   kor=u'에스겔',         en='Ezek',  eng='Ezekiel'),
    Entry('Dan',   ko=u'단',   kor=u'다니엘',         en='Dan',   eng='Daniel'),
    Entry('Hos',   ko=u'호',   kor=u'호세아',         en='Hos',   eng='Hosea'),
    Entry('Joel',  ko=u'욜',   kor=u'요엘',           en='Joel',  eng='Joel'),
    Entry('Amos',  ko=u'암',   kor=u'아모스',         en='Amos',  eng='Amos'),
    Entry('Obad',  ko=u'옵',   kor=u'오바댜',         en='Obad',  eng='Obadiah'),
    Entry('Jnah',  ko=u'욘',   kor=u'요나',           en='Jnah',  eng='Jonah'),
    Entry('Mic',   ko=u'미',   kor=u'미가',           en='Mic',   eng='Micah'),
    Entry('Nah',   ko=u'나',   kor=u'나훔',           en='Nah',   eng='Nahum'),
    Entry('Hab',   ko=u'합',   kor=u'하박국',         en='Hab',   eng='Habakkuk'),
    Entry('Zeph',  ko=u'습',   kor=u'스바냐',         en='Zeph',  eng='Zephaniah'),
    Entry('Hag',   ko=u'학',   kor=u'학개',           en='Hag',   eng='Haggai'),
    Entry('Zech',  ko=u'슥',   kor=u'스가랴',         en='Zech',  eng='Zechariah'),
    Entry('Mal',   ko=u'말',   kor=u'말라기',         en='Mal',   eng='Malachi'),
    Entry('Matt',  ko=u'마',   kor=u'마태복음',       en='Matt',  eng='Matthew'),
    Entry('Mark',  ko=u'막',   kor=u'마가복음',       en='Mark',  eng='Mark'),
    Entry('Luke',  ko=u'눅',   kor=u'누가복음',       en='Luke',  eng='Luke'),
    Entry('John',  ko=u'요',   kor=u'요한복음',       en='John',  eng='John'),
    Entry('Acts',  ko=u'행',   kor=u'사도행전',       en='Acts',  eng='Acts'),
    Entry('Rom',   ko=u'롬',   kor=u'로마서',         en='Rom',   eng='Romans'),
    Entry('1Cor',  ko=u'고전', kor=u'고린도전서',     en='1Cor',  eng='1 Corinthians'),
    Entry('2Cor',  ko=u'고후', kor=u'고린도후서',     en='2Cor',  eng='2 Corinthians'),
    Entry('Gal',   ko=u'갈',   kor=u'갈라디아서',     en='Gal',   eng='Galatians'),
    Entry('Eph',   ko=u'엡',   kor=u'에베소서',       en='Eph',   eng='Ephesians'),
    Entry('Phlm',  ko=u'빌',   kor=u'빌립보서',       en='Phlm',  eng='Philippians'),
    Entry('Col',   ko=u'골',   kor=u'골로새서',       en='Col',   eng='Colossians'),
    Entry('1Thes', ko=u'살전', kor=u'데살로니가전서', en='1Thes', eng='1 Thessalonians'),
    Entry('2Thes', ko=u'살후', kor=u'데살로니가후서', en='2Thes', eng='2 Thessalonians'),
    Entry('1Tim',  ko=u'딤전', kor=u'디모데전서',     en='1Tim',  eng='1 Timothy'),
    Entry('2Tim',  ko=u'딤후', kor=u'디모데후서',     en='2Tim',  eng='2 Timothy'),
    Entry('Titus', ko=u'딛',   kor=u'디도서',         en='Titus', eng='Titus'),
    Entry('Phle',  ko=u'몬',   kor=u'빌레몬서',       en='Phle',  eng='Philemon'),
    Entry('Heb',   ko=u'히',   kor=u'히브리서',       en='Heb',   eng='Hebrews'),
    Entry('James', ko=u'약',   kor=u'야고보서',       en='James', eng='James'),
    Entry('1Pet',  ko=u'벧전', kor=u'베드로전서',     en='1Pet',  eng='1 Peter'),
    Entry('2Pet',  ko=u'벧후', kor=u'베드로후서',     en='2Pet',  eng='2 Peter'),
    Entry('1John', ko=u'요일', kor=u'요한일서',       en='1John', eng='1 John'),
    Entry('2John', ko=u'요이', kor=u'요한이서',       en='2John', eng='2 John'),
    Entry('3John', ko=u'요삼', kor=u'요한삼서',       en='3John', eng='3 John'),
    Entry('Jude',  ko=u'유',   kor=u'유다서',         en='Jude',  eng='Jude'),
    Entry('Rev',   ko=u'계',   kor=u'요한계시록',     en='Rev',   eng='Revelation'),
)

