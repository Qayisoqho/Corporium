"""Field-aware morpheme search using the dictionary's matching semantics."""
import json
from collections import defaultdict
import grammar
from dictionary_search import SearchIndex, label, BASE_PATHS

class MorphemeIndex(SearchIndex):
    def __init__(self, db, lid, rows,catalog_only=False):
        self.classes=[];self.classmap={};self.names={};self.people={};self.paths={}
        self.types={r['id']:r['name'] for r in db.execute("SELECT id,name FROM writing_types WHERE ?='all' OR language_id=?",(lid,lid))}
        self.names.update(self.types)
        self.tags={r['id']:r for r in grammar.listing(db,lid)}
        paths=['form','gloss','definition','tags','entry_type','affix_function','affix_position','readings','notes','source','role','segments','features','writings','writings.text','senses','senses.gloss','senses.definition','senses.tags','usages']
        paths += [p for p in BASE_PATHS if p=='variants' or p.startswith('variants.')]
        self.fields={p:label(p) for p in paths}
        self.fields.update(form='语素形式',gloss='简短标注',writings='书写形式',definition='意义／功能',entry_type='语素类型',affix_function='构词功能',affix_position='词缀位置')
        self.extra=defaultdict(lambda:defaultdict(list));self.layer_values=defaultdict(lambda:defaultdict(list))
        for key,name in self.types.items():self.fields['writing:'+key]='自定义书写 › '+name
        self.documents={}
        if catalog_only:
            self.discover(row['body'] for row in rows)
            return
        for row in rows:
            body=dict(row['body'])
            if body.get('entry_type') not in ('affix','infix','circumfix'):
                body.pop('affix_function',None);body.pop('affix_position',None)
            doc=self.document({**row,'body':body,'headword':row['form']})
            doc['form']=doc.pop('headword',[])
            self.documents[row['id']]=doc
        self.fields.pop('headword',None)
    def catalog(self):
        return {'fields':[{'id':'all','name':'语素全部内容'}]+[{'id':k,'name':v} for k,v in self.fields.items()], 'classes':[]}

def catalog(db,lid):
    rows=[{**dict(r),'body':json.loads(r['body'])} for r in db.execute("SELECT * FROM morphemes WHERE ?='all' OR language_id=?",(lid,lid))]
    return MorphemeIndex(db,lid,rows,catalog_only=True).catalog()
