"""Read-only discovery hints. Never an official language inventory.

Abbreviations follow the Leipzig Glossing Rules appendix; Chinese descriptions
and broad search categories are editorial aids, not analyses of any language.
"""
VERSION='2026-10-23.1'
SOURCE='https://www.eva.mpg.de/lingua/resources/glossing-rules.php'
_ROWS='''1|第一人称|人称
2|第二人称|人称
3|第三人称|人称
A|及物动词的施事论元|论元
ABL|离格|格
ABS|通格|格
ACC|宾格|格
ADJ|形容词|词类
ADV|副词／副词性|词类
AGR|一致|一致
ALL|向格|格
ANTIP|反被动|语态
APPL|应动态|语态
ART|冠词|词类
AUX|助动词|词类
BEN|受益格|格
CAUS|致使态|语态
CLF|分类词|词类
COM|伴随格|格
COMP|补语标记|从属
COMPL|完结体|体
COND|条件式|语式
COP|系词|词类
CVB|副动词|从属
DAT|与格|格
DECL|陈述式|语式
DEF|定指|指称
DEM|指示词|指称
DET|限定词|词类
DIST|远指|指称
DISTR|分配|数
DU|双数|数
DUR|持续体|体
ERG|作格|格
EXCL|排除式|人称
F|阴性|性
FOC|焦点|信息结构
FUT|将来时|时
GEN|属格|格
IMP|命令式|语式
INCL|包括式|人称
IND|直陈式|语式
INDF|不定指|指称
INF|不定式|从属
INS|工具格|格
INTR|不及物|及物性
IPFV|未完整体|体
IRR|非现实|语式
LOC|处所格|格
M|阳性|性
N|中性|性
NEG|否定|极性
NMLZ|名物化|派生
NOM|主格|格
OBJ|宾语|论元
OBL|斜格／非核心论元|论元
P|及物动词的受事论元|论元
PASS|被动|语态
PFV|完整体|体
PL|复数|数
POSS|领属|领属
PRED|谓语性|句法
PRF|完成体|时体
PRS|现在时|时
PROG|进行体|体
PROH|禁止式|语式
PROX|近指|指称
PST|过去时|时
PTCP|分词|从属
PURP|目的|从属
Q|疑问|语式
QUOT|引述|示证
RECP|相互态|语态
REFL|自反态|语态
REL|关系化|从属
RES|结果体|体
S|不及物动词的唯一论元|论元
SBJ|主语|论元
SBJV|虚拟式|语式
SG|单数|数
TOP|话题|信息结构
TR|及物|及物性
VOC|呼格|格'''
ROWS=tuple(dict(zip(('symbol','description','category'),line.split('|')),source=SOURCE) for line in _ROWS.splitlines())
INDEX={row['symbol'].casefold():row for row in ROWS}
# Lower-case English homographs are weak evidence, even when a reference exists.
# Explicitly registered tags/aliases remain authoritative for compatibility.
LEXICAL=frozenset(('a','all','art','pass'))

def find(symbol):
    return INDEX.get(symbol.casefold())

def candidate(symbol):
    row=find(symbol)
    return bool(row and (symbol==row['symbol'] or len(symbol)>1 and symbol.casefold() not in LEXICAL))
