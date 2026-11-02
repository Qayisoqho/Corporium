"""MPW from the form row's cells, independent of dictionary associations."""
import re
from collections import OrderedDict
import corpus


def cells(form):
    """Mirror form-row splitting: protect scripts and angle-delimited material."""
    ranges=[m.span() for m in re.finditer(r'<[^<]*>',form)]
    parts=[];start=depth=0
    for i,char in enumerate(form):
        if char=='[':depth+=1
        elif char==']':depth=max(0,depth-1)
        elif not depth and char in '-＝=+~' and not any(a<=i<b for a,b in ranges):
            parts.append((form[start:i],char));start=i+1
    parts.append((form[start:],''))
    morphemes=sum(bool(corpus.plain(value).strip()) for value,_ in parts)
    # A standalone =clitic already occupies a word slot. Empty = segments do
    # not invent words; affixes attached to one clitic do not add another word.
    groups=[];has_content=False
    for value,separator in parts:
        has_content|=bool(corpus.plain(value).strip())
        if separator in ('=','＝'):
            groups.append(has_content);has_content=False
    groups.append(has_content)
    return morphemes,max(0,sum(groups)-1)


def result(morphemes,slots,clitics,separate):
    words=slots+(clitics if separate else 0)
    return dict(morphemes=morphemes,word_slots=slots,clitic_words=clitics,
                words=words,value=morphemes/words if words else None,separate_clitics=separate)


class Counter:
    def __init__(self,word_counter,separate=False):
        self.word_counter=word_counter;self.separate=separate
        self.cache=OrderedDict();self.bytes=0
        self.morphemes=self.slots=self.clitics=0

    def record(self,words):
        morphemes=slots=clitics=0
        for word in words:
            if not self.word_counter(word):continue
            form=word.get('form','')
            if form in self.cache:
                counts=self.cache[form];self.cache.move_to_end(form)
            else:
                counts=cells(form);cost=160+4*len(form)
                if cost<=1024**2:
                    while self.cache and (len(self.cache)>=4096 or self.bytes+cost>4*1024**2):
                        old,_=self.cache.popitem(last=False);self.bytes-=160+4*len(old)
                    self.cache[form]=counts;self.bytes+=cost
            morphemes+=counts[0];clitics+=counts[1];slots+=1
        self.morphemes+=morphemes;self.slots+=slots;self.clitics+=clitics
        return result(morphemes,slots,clitics,self.separate)

    def finish(self):return result(self.morphemes,self.slots,self.clitics,self.separate)
