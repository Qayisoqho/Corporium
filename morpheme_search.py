"""Field-aware morpheme search using the dictionary's matching semantics."""
import json
from collections import defaultdict
import grammar
from dictionary_search import SearchIndex, label, BASE_PATHS

class MorphemeIndex(SearchIndex):
    def __init__(self, db, lid, rows,catalog_only=False,search_spec=None,query=None):
        projected=[]
        for r in rows:
            body=dict(r['body'])
            if body.get('entry_type') not in ('affix','infix','circumfix'):
                body.pop('affix_function',None);body.pop('affix_position',None)
            projected.append({**r,'headword':r['form'],'body':body})
        super().__init__(db,lid,projected,catalog_only=catalog_only,search_spec=search_spec,query=query)
        paths=['form','gloss','definition','tags','entry_type','affix_function','affix_position','readings','notes','source','role','segments','features','writings','writings.text','senses','senses.gloss','senses.definition','senses.tags','usages']
        paths += [p for p in BASE_PATHS if p=='variants' or p.startswith('variants.')]
        # Reuse evidence matching without presenting empty word-only categories.
        evidence={k:v for k,v in self.fields.items() if k.startswith(('writing:','layer:','tag:','examples.')) or k=='examples'}
        self.fields={p:label(p) for p in paths};self.fields.update(evidence)
        self.discover(r['body'] for r in projected)
        self.fields.update(form='语素形式',gloss='简短标注',writings='书写形式',definition='意义／功能',entry_type='语素类型',affix_function='构词功能',affix_position='词缀位置')
        for doc in self.documents.values() if not catalog_only else []:doc['form']=doc.pop('headword',[])
        self.fields.pop('headword',None)
        self.classes=[]
    def catalog(self):
        return {'fields':[{'id':'all','name':'语素全部内容'}]+[{'id':k,'name':v} for k,v in self.fields.items()], 'classes':[]}

def catalog(db,lid):
    rows=[{**dict(r),'body':json.loads(r['body'])} for r in db.execute("SELECT * FROM morphemes WHERE ?='all' OR language_id=?",(lid,lid))]
    return MorphemeIndex(db,lid,rows,catalog_only=True).catalog()
