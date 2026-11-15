"""Field-aware morpheme search using the dictionary's matching semantics."""
from collections import defaultdict
import grammar
from dictionary_search import SearchIndex, label, BASE_PATHS

AFFIX_TYPES = ('affix','infix','circumfix')


def project_row(row):
    body=dict(row['body'])
    if body.get('entry_type') not in AFFIX_TYPES:
        body.pop('affix_function',None);body.pop('affix_position',None)
    return {**row,'headword':row['form'],'body':body}


class MorphemeIndex(SearchIndex):
    def __init__(self, db, lid, rows,catalog_only=False,search_spec=None,query=None,**options):
        projected=[project_row(r) for r in rows]
        super().__init__(db,lid,projected,catalog_only=catalog_only,search_spec=search_spec,query=query,
                         evidence_kinds=('morpheme',),**options)
        paths=['form','gloss','definition','tags','entry_type','affix_function','affix_position','readings','notes','source','role','segments','features','writings','writings.text','senses','senses.gloss','senses.definition','senses.tags','usages']
        paths += [p for p in BASE_PATHS if p=='variants' or p.startswith('variants.')]
        # Reuse evidence matching without presenting empty word-only categories.
        evidence={k:v for k,v in self.fields.items() if k.startswith(('writing:','layer:','tag:','examples.')) or k=='examples'}
        self.fields={p:label(p) for p in paths};self.fields.update(evidence)
        self.discover(r['body'] for r in projected)
        self.fields.update(form='语素形式',gloss='简短标注',writings='书写形式',definition='意义／功能',entry_type='语素类型',affix_function='构词功能',affix_position='词缀位置')
        for doc in getattr(self,'documents',{}).values():doc['form']=doc.pop('headword',[])
        self.fields.pop('headword',None)
        self.classes=[]
    def catalog(self):
        return {'fields':[{'id':'all','name':'语素全部内容'}]+[{'id':k,'name':v} for k,v in self.fields.items()], 'classes':[]}

def catalog(db,lid):
    import material_search_index
    import record_sources
    if record_sources.native(db):
        import dictionary_option_catalog
        return dictionary_option_catalog.read(db,'morpheme',lid)
    cached=material_search_index.catalog(db,'morpheme',lid)
    if cached is not None:return cached
    scope,args=('',()) if lid=='all' else (' WHERE language_id=?',(lid,))
    rows=record_sources.with_bodies(db,'morphemes',db.execute('SELECT * FROM morphemes'+scope+' ORDER BY rowid',args))
    result=MorphemeIndex(db,lid,rows,catalog_only=True).catalog()
    material_search_index.catalog(db,'morpheme',lid,result)
    return result
