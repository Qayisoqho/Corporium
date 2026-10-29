"""Loss-preserving parser for the corpus's Typst call subset; never executes Typst."""
import re
import long_tasks
import unicodedata
import segmentation
import json
from collections import OrderedDict


def compact_gloss(text):
    """Join filled annotation cells; no separator survives without both neighbours."""
    previous=None
    while previous!=text:
        previous=text
        text=re.sub(r'#(?:sub|sup|super)\[\s*\]|\[\s*\]','',text)
    parts=[];start=0;depth=0
    angles=[(m.start(),m.end()) for m in re.finditer(r'<[^<]*>',text)]
    for i,char in enumerate(text):
        if char=='[':depth+=1
        elif char==']':depth=max(0,depth-1)
        elif not depth and not any(a<=i<b for a,b in angles) and char in '-.＝=:+/>;\\':
            parts.extend((text[start:i],char));start=i+1
    parts.append(text[start:])
    result=[];pending='';filled=False
    for i,value in enumerate(parts):
        if i%2:
            if filled and (not pending or value in '-＝=+'):pending=value
        elif value.strip():
            result.extend((pending,value));pending='';filled=True
    return ''.join(result)


def compact_empty_pairs(form,gloss):
    """Remove empty paired morpheme cells without removing a nonempty form."""
    if not re.sub(r'[\s\-=+~<>＝]','',form) and not re.sub(r'[\s\-=+~<>＝.]','',gloss):return '',''
    fs=segmentation.split_parts(form);gs=segmentation.split_parts(gloss)
    if len(fs)!=len(gs) or [p[2] for p in fs]!=[p[2] for p in gs]:return form,gloss
    keep=[i for i,(f,g) in enumerate(zip(fs,gs)) if f[0].strip() or g[0].strip()]
    def join(parts):return ''.join((parts[i-1][2] if n and i else '')+parts[i][0] for n,i in enumerate(keep))
    return join(fs),join(gs)


def normalize_edited_pair(form,gloss):
    """Clean empty edit cells, then recheck the actual morpheme boundaries.

    Dot-separated labels stay within one morpheme. An unmatched empty form cell
    can be removed only if that restores the same boundary sequence as the gloss;
    nonempty forms and genuinely different analyses are never rewritten to fit.
    """
    form,gloss=compact_empty_pairs(form,gloss)
    gloss=compact_gloss(gloss)
    signature=lambda value:[p[2] for p in segmentation.split_parts(value)]
    if signature(form)!=signature(gloss) and '\\' not in form:
        parts=segmentation.split_parts(form);keep=[i for i,p in enumerate(parts) if p[0].strip()]
        if keep:
            candidate=''.join((parts[i-1][2] if n else '')+parts[i][0] for n,i in enumerate(keep))
            if signature(candidate)==signature(gloss):form=candidate
    return compact_empty_pairs(form,gloss)


def compact_edited_pairs(words,previous=()):
    """Full/Tab editors use the same cleanup, without rewriting untouched pairs."""
    known={(w['form'],w['gloss']) for w in previous};result=[];positions={}
    for i,word in enumerate(words):
        form,gloss=word['form'],word['gloss']
        if not isinstance(form,str) or not isinstance(gloss,str):raise ValueError('语素和标注须为文本')
        if (form,gloss) not in known:
            form,gloss=normalize_edited_pair(form,gloss)
        if form.strip() or gloss.strip():
            positions[i]=len(result);result.append({**word,'form':form,'gloss':gloss})
    return result,positions


class ParseError(ValueError):
    pass


class Parser:
    def __init__(self, source):
        self.s, self.i = source, 0

    def skip(self):
        while self.i < len(self.s):
            if self.i%4096==0:long_tasks.checkpoint()
            if self.s[self.i].isspace():
                self.i += 1
            elif self.s.startswith('//', self.i):
                end = self.s.find('\n', self.i)
                self.i = len(self.s) if end < 0 else end + 1
            elif self.s.startswith('/*', self.i):
                self.i += 2
                depth = 1
                while depth and self.i < len(self.s):
                    if self.i%4096==0:long_tasks.checkpoint()
                    if self.s.startswith('/*', self.i):
                        depth += 1
                        self.i += 2
                    elif self.s.startswith('*/', self.i):
                        depth -= 1
                        self.i += 2
                    else:
                        self.i += 1
                if depth:
                    raise ParseError('未闭合的块注释')
            else:
                break

    def value(self):
        self.skip()
        start = self.i
        if self.i >= len(self.s):
            raise ParseError('意外到达文件末尾')
        c = self.s[self.i]
        self.i += 1
        if c == '(':
            values = []
            while True:
                self.skip()
                if self.i >= len(self.s):
                    raise ParseError('未闭合的圆括号')
                if self.s[self.i] == ')':
                    self.i += 1
                    return values
                values.append(self.value())
                self.skip()
                if self.i < len(self.s) and self.s[self.i] == ',':
                    self.i += 1
                elif self.i >= len(self.s) or self.s[self.i] != ')':
                    raise ParseError('预期逗号或右圆括号')
        if c in '["':
            depth = 1
            while self.i < len(self.s):
                if self.i%4096==0:long_tasks.checkpoint()
                char = self.s[self.i]
                if char == '\\':
                    self.i += 2
                    continue
                if c == '[' and char == '[':
                    depth += 1
                if (c == '[' and char == ']') or (c == '"' and char == '"'):
                    depth -= 1
                    if not depth:
                        self.i += 1
                        raw = self.s[start:self.i]
                        return {'text': raw[1:-1], 'kind': 'content' if c == '[' else 'string', 'raw': raw}
                self.i += 1
            raise ParseError('未闭合的文本字段')
        raise ParseError('仅支持圆括号元组、方括号内容和双引号字符串')


def plain(text):
    text = re.sub(r'#sub\[([^\[\]]*)\]', r'\1', text)
    return re.sub(r'\\([\\"\[\]#~?])', r'\1', text)


def clean(text):
    return plain(text).strip(' \t\r\n«»“”\".,;:!?…。，；：！？')


def normalize(text, case=False):
    text = unicodedata.normalize('NFC', text)
    return text if case else text.casefold()


def boundary_count(form):
    """Only a complete hash-only cell denotes a phonological boundary."""
    value = form.strip().replace('\\#', '#')
    return len(value) if re.fullmatch(r'#+', value) else 0


def split_gloss_morphemes(text):
    """Only outside brackets can a connector introduce another morpheme."""
    parts, separators, start, depth = [], [], 0, 0
    for i, char in enumerate(text):
        if char == '[': depth += 1
        elif char == ']': depth = max(0, depth-1)
        elif depth == 0 and char in '-=+~':
            parts.append(text[start:i]);separators.append(char);start=i+1
    parts.append(text[start:])
    return parts, separators


def gloss_chunks(text):
    """Return text and whether it is explicitly enclosed as grammatical material."""
    depth, start = 0, 0
    for i, char in enumerate(text):
        if char in '[]':
            if i > start: yield text[start:i], depth > 0
            depth = depth+1 if char == '[' else max(0, depth-1)
            start = i+1
    if start < len(text): yield text[start:], depth > 0


def gloss_relations(gloss):
    """Keep the ordered sides of > within each morpheme, without splitting words."""
    result = []
    for index, part in enumerate(split_gloss_morphemes(plain(gloss))[0]):
        try:
            groups,_=segmentation.angles(part,True)
            values=[part[a:b] for a,b in segmentation.gaps(len(part),groups)]+[g[2] for g in groups]
        except ValueError:values=[]
        for value in values:
            sides = value.split('>')
            if len(sides) > 1:
                result.append({'morpheme': index, 'operator': '>', 'sides': [s.strip() for s in sides]})
    return result


class WordAnalysisCache:
    """Operation-local, byte-bounded reuse; every hit gets independent data."""
    def __init__(self,limit=8*1024**2,items=512):
        self.limit=limit;self.items=items;self.bytes=0;self.values=OrderedDict()

    def apply(self,word,position):
        # Analysis reads these source fields only. Occurrence IDs and previously
        # derived segments do not change the result and must not multiply work.
        inputs=('form','gloss','punctuation','punctuation_form','morph_groups','infix_confirmation')
        source={k:word[k] for k in inputs if k in word}
        key=json.dumps(source,ensure_ascii=False,sort_keys=True).encode('utf-8')
        saved=self.values.get(key)
        if saved is None:
            result=_analyze(dict(ipa='',translation='',words=[source]))
            warnings=result['warnings']
            derived={k:v for k,v in source.items() if k not in inputs or k=='punctuation'}
            saved=json.dumps([derived,warnings],ensure_ascii=False).encode('utf-8')
            size=len(key)+len(saved)
            if size<=self.limit and self.items>0:
                while self.values and (self.bytes+size>self.limit or len(self.values)>=self.items):
                    old,value=self.values.popitem(last=False);self.bytes-=len(old)+len(value)
                self.values[key]=saved;self.bytes+=size
        else:self.values.move_to_end(key)
        # Only derived values are overlaid. Keep identity, notes and even legacy
        # analysis_form on failed parsing, exactly as the full analyzer does.
        analyzed,warnings=json.loads(saved);word.update(analyzed)
        return [w.replace('第 1 ',f'第 {position+1} ',1) for w in warnings]


def analyze(entry,*,cache=None):
    if cache is None:return _analyze(entry)
    warnings=[]
    for n,word in enumerate(entry['words']):warnings.extend(cache.apply(word,n))
    return _finish_analysis(entry,warnings)


def reanalyze(entry,previous,positions,*,cache=None):
    """Internal fixed-slot edits of a freshly analyzed sentence, in this call.

    Unchanged words are reused, never trusted from persisted derived data.
    Rebuild word warnings in sentence order, then all sentence/reference checks.
    """
    if len(entry['words'])!=len(previous['words']):return analyze(entry,cache=cache)
    by_position={}
    for warning in previous['warnings']:
        match=re.match(r'^第 (\d+) [词格]：',warning)
        if match:by_position.setdefault(int(match[1])-1,[]).append(warning)
    warnings=[]
    for n,word in enumerate(entry['words']):
        if n in positions:
            if cache is not None:warnings.extend(cache.apply(word,n))
            else:
                one=_analyze(dict(ipa='',translation='',words=[word]))
                warnings.extend(w.replace('第 1 ',f'第 {n+1} ',1) for w in one['warnings'])
        else:
            entry['words'][n]=previous['words'][n]
            warnings.extend(by_position.get(n,[]))
    return _finish_analysis(entry,warnings)


def _analyze(entry):
    warnings = []
    for n, word in enumerate(entry['words']):
        count = boundary_count(word['form'])
        punct=bool(word.get('punctuation') and word.get('punctuation_form')==word['form'] and not word['gloss'].strip())
        word['punctuation']=punct
        word.update(unit_type='punctuation' if punct else 'phonological_boundary' if count else 'word', boundary_count=count,
                    gloss_relations=[] if count else gloss_relations(word['gloss']))
        word.update(segments=[],group_reviews=[],infix_ambiguous=False)
        if count or punct:
            word['morphemes'] = []
            word['group_reviews']=word.get('morph_groups',[])
            continue
        if word['form'].strip() and not word['gloss'].strip() and all(c in '。，、；：？！.,;:?!…«»“”‘’\"\'（）()【】[]' for c in word['form'].strip()):
            warnings.append(f'第 {n+1} 格：可能是标点，请使用“应用自动识别标点”预览确认；已有标注或关联须人工核对')
        form, gloss = clean(word['form']), clean(word['gloss'])
        try:issue=segmentation.analyze_word(word,form,gloss)
        except ValueError as exc:
            word['morphemes']=[];issue=str(exc);word['group_reviews']=word.get('morph_groups',[])
        if issue:warnings.append(f'第 {n+1} 词：'+issue)
        for key in ('form', 'gloss'):
            if '#' in re.sub(r'#sub\[[^\[\]]*\]', '', word[key]):
                warnings.append(f'第 {n+1} 词：含未支持的 Typst 命令，保留源码显示')
    return _finish_analysis(entry,warnings)


def _finish_analysis(entry,warnings):
    import reduplication
    reduplication.decorate(entry,warnings)
    for key in ('ipa', 'translation'):
        if '#' in entry[key]:
            warnings.append(f'{key} 含 Typst 命令，保留源码显示')
    if entry.get('orphaned_morphology'):warnings.append('有无法定位原词的旧形态组合，请在形态分析中核对')
    entry['warnings'] = warnings
    segmentation.decorate_refs(entry)
    return entry


def parse(source, *, analyze_entries=True):
    p = Parser(source)
    entries, errors = [], []
    while p.i < len(source):
        long_tasks.checkpoint()
        try:
            p.skip()
        except ParseError as exc:
            errors.append({'line': source.count('\n', 0, p.i)+1, 'message': str(exc)})
            break
        m = re.match(r'#(gloss|pass)\s*(?=\()', source[p.i:])
        if not m:
            p.i += 1
            continue
        start = p.i
        line = source.count('\n', 0, start)+1
        p.i += len(m.group())
        try:
            args = p.value()
            if len(args) != 3 or not isinstance(args[0], dict) or not isinstance(args[1], list) or not isinstance(args[2], dict):
                raise ParseError('调用应包含 IPA、配对元组、翻译三个参数')
            words = []
            for pair in args[1]:
                if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(v, dict) for v in pair):
                    raise ParseError('每个词必须是两个文本字段组成的配对')
                words.append({'form': pair[0]['text'], 'gloss': pair[1]['text'], 'form_kind': pair[0]['kind'], 'gloss_kind': pair[1]['kind']})
            entry={'function': m[1], 'ipa': args[0]['text'], 'translation': args[2]['text'], 'words': words, 'raw': source[start:p.i], 'line': line, 'edited': False}
            import reduplication
            reduplication.import_prefix(source,start,entry)
            entries.append(analyze(entry) if analyze_entries else entry)
        except (ValueError, TypeError, KeyError) as exc:
            errors.append({'line': line, 'message': str(exc), 'raw': source[start:p.i]})
            next_call = re.search(r'(?m)^\s*#(?:gloss|pass)\s*\(', source[max(p.i, start+1):])
            if not next_call:
                break
            p.i = max(p.i, start+1)+next_call.start()
    return entries, errors


def export_entry(entry):
    import reduplication
    prefix=reduplication.export_prefix(entry)
    if not entry.get('edited') and entry.get('raw'):
        return prefix+entry['raw']
    def field(text, kind='content'):
        if kind == 'string':
            return '"' + text + '"'
        return '[' + text + ']'
    pairs = ',\n'.join('  ('+field(w['form'], w.get('form_kind'))+', '+field(w['gloss'], w.get('gloss_kind'))+')' for w in entry['words'])
    return prefix+'#'+entry['function']+'(\n['+entry['ipa']+'],\n(\n'+(pairs+',\n' if pairs else '')+'),\n['+entry['translation']+'],\n)'


def match(entry, query, field, exact=False, case=False, mode=None, *, _gloss_cache=None):
    q = normalize(query, case)
    mode = mode or ('exact' if exact else 'contains')
    def hit(s):
        s = normalize(s, case)
        if mode == 'exact':
            return s == q
        if mode == 'prefix':
            return s.startswith(q)
        if mode == 'suffix':
            return s.endswith(q)
        return q in s
    if field=='reduplication':
        import reduplication
        indices=[i for i,values in reduplication.index(entry).items() if not q or any(hit(v) for v in values)]
        indices.sort()
        return indices,bool(indices)
    if not q:
        return [], True
    indices = []
    for i, w in enumerate(entry['words'] if field in ('form','morpheme','gloss','all') else []):
        if field in ('gloss','form','all') and _gloss_cache is not None:
            if _gloss_cache.word_hit(w,hit):indices.append(i)
            continue
        if boundary_count(w['form']) and field in ('form', 'morpheme', 'gloss'):
            continue
        values = ([clean(w['form'])] if field == 'form' else
                  [m['form'] for m in analyze({'ipa':'','translation':'','words':[dict(w)]})['words'][0]['morphemes']] if field == 'morpheme' else
                  split_gloss_morphemes(clean(w['gloss']))[0] + re.findall(r'#sub\[([^]]*)\]', w['gloss']) if field == 'gloss' else
                  [plain(w['form']), plain(w['gloss'])] if field == 'all' else [])
        if any(hit(v) for v in values):
            indices.append(i)
    other = any(hit(plain(entry.get(k,''))) for k in ('ipa', 'translation', 'notes', 'language_notes', 'text_notes') if field in (k, 'all') or (field=='notes' and k in ('language_notes','text_notes')))
    return indices, bool(indices or other)


class QueryMatcher:
    """One query's bounded word matches; positions and counts stay per sentence."""
    def __init__(self,query,field,exact=False,case=False,mode=None,*,max_entries=4096,max_bytes=4*1024**2):
        self.options=(query,field,exact,case,mode)
        self.max_entries=max_entries;self.max_bytes=max_bytes
        self.hits=OrderedDict();self.bytes=0

    def __call__(self,entry):return match(entry,*self.options,_gloss_cache=self)

    def word_hit(self,word,hit):
        key=(word['form'],word['gloss']);saved=self.hits.get(key)
        if saved is not None:
            self.hits.move_to_end(key);return saved[0]
        field=self.options[1]
        if field=='all':result=any(hit(plain(word[k])) for k in ('form','gloss'))
        elif boundary_count(word['form']):result=False
        elif field=='form':result=hit(clean(word['form']))
        else:result=any(hit(v) for v in split_gloss_morphemes(clean(word['gloss']))[0]+re.findall(r'#sub\[([^]]*)\]',word['gloss']))
        size=256+4*sum(map(len,key))
        if self.max_entries>0 and size<=self.max_bytes:
            while self.hits and (len(self.hits)>=self.max_entries or self.bytes+size>self.max_bytes):
                _,(_,cost)=self.hits.popitem(last=False);self.bytes-=cost
            self.hits[key]=(result,size);self.bytes+=size
        return result
