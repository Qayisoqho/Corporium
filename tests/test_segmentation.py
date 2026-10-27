import json
import unittest
import corpus
import grammar
import server
import test_lexicon
from restore_backup import restore


class SegmentationTests(unittest.TestCase):
    setUp=test_lexicon.LexiconTests.setUp
    tearDown=test_lexicon.LexiconTests.tearDown
    call=test_lexicon.LexiconTests.call
    seed=test_lexicon.LexiconTests.seed
    entries=test_lexicon.LexiconTests.entries
    undo=test_lexicon.LexiconTests.undo

    def get(self,e,kind='corpus'):
        code,d=self.call('/api/segmentation?kind='+kind+'&id='+e['id']);self.assertEqual(code,200,d);return d

    def group(self,e,kind='corpus',members=None,**extra):
        d=self.get(e,kind)
        b=dict(kind=kind,id=e['id'],revision=d['revision'],action='save',word=0,members=members or ['0:host','2:host'],type='circumfix',status='confirmed',gloss='PST')
        b.update(extra);code,r=self.call('/api/segmentation-save',b);self.assertEqual(code,200,r)
        return self.get(e,kind)

    def word(self,headword='we…la'):
        code,x=self.call('/api/lexeme-save',dict(headword=headword,body={'variants':[{'form':headword}], 'usages':[{'pos':'AFF','senses':[{'short_gloss':'PST'}]}]}))
        self.assertEqual(code,200,x);return x

    def link(self,d,x,key,kind='corpus'):
        payload=dict(kind=kind,id=d['id'],revision=d['revision'],word=0,key=key,lexeme_id=x['id'],lexeme_revision=x['revision'],form_id=x['body']['variants'][0]['id'],usage_id=x['body']['usages'][0]['id'],sense_id=x['body']['usages'][0]['senses'][0]['id'])
        code,r=self.call('/api/segmentation-link',payload);self.assertEqual(code,200,r);return payload

    def test_infix_hosts_repeated_left_right_and_invalid(self):
        for form,gloss in [('so<l><u>ma','home<nom.pl><emph>'),('so<l>m<u>a','<nom.pl><emph>home')]:
            e=corpus.analyze(dict(ipa='',translation='',words=[dict(form=form,gloss=gloss)]));w=e['words'][0]
            self.assertEqual(e['warnings'],[])
            self.assertEqual([m['gloss'] for m in w['morphemes']],['home','nom.pl','emph'])
            self.assertEqual(w['morphemes'][0]['lookup_form'],'soma')
            self.assertEqual(''.join(f['text'] for f in w['morphemes'][0]['fragments']),'soma')
            for m in w['morphemes']:
                for f in m['fragments']:self.assertEqual(form[f['start']:f['end']],f['text'])
        for form,gloss in [('so<l>ma','home'),('so<lma','home<nom>'),('so<l>ma','home<nom><pl>')]:
            e=corpus.analyze(dict(ipa='',translation='',words=[dict(form=form,gloss=gloss)]))
            self.assertTrue(e['warnings']);self.assertEqual(e['words'][0]['morphemes'],[])
        self.assertEqual(list(grammar.tokens('home<nom.pl>','ordos',{},candidates=True)),['nom','pl'])

    def test_relation_closing_disambiguation(self):
        e=self.seed('#pass([], (([so<l>ma],[home<s.1>o.3sg>]),), [])')
        d=self.get(e);self.assertTrue(d['body']['words'][0]['infix_ambiguous'])
        self.assertEqual(d['body']['words'][0]['morphemes'],[])
        code,r=self.call('/api/segmentation-save',dict(kind='corpus',id=e['id'],revision=d['revision'],word=0,action='confirm-infix'))
        self.assertEqual(code,200,r)
        w=self.entries()[0]['words'][0]
        self.assertEqual(w['morphemes'][1]['gloss'],'s.1>o.3sg')
        self.assertEqual(w['gloss_relations'][0]['sides'],['s.1','o.3sg'])
        self.assertEqual(corpus.gloss_relations('home<nom.pl>'),[])
        self.assertEqual(self.undo()[0],200);self.assertTrue(self.get(e)['body']['words'][0]['infix_ambiguous'])

    def test_group_link_undo_and_changed_word_review(self):
        source='#pass([], (([we-amos-la],[pst-go-pst]),), [])'
        e=self.seed(source);d=self.group(e);w=d['body']['words'][0]
        self.assertEqual([m['form'] for m in w['morphemes']],['we…la','amos'])
        self.assertEqual(self.call('/api/export?id='+e['text_id'])[1],source)
        x=self.word();payload=self.link(d,x,w['morphemes'][0]['key'])
        self.assertEqual(self.call('/api/segmentation-link',payload)[0],400)
        evidence=self.call('/api/lexeme-examples?id='+x['id'])[1]
        self.assertEqual(evidence['total'],1);self.assertEqual(evidence['items'][0]['form'],'we…la')
        current=self.entries()[0];current['words'][0]['form']='wu-amos-la';current['notes']=''
        self.assertEqual(self.call('/api/save',current)[0],200)
        fresh=self.entries()[0]['words'][0]
        self.assertEqual(len(fresh['group_reviews']),1)
        self.assertTrue(self.call('/api/lexeme-examples?id='+x['id'])[1]['items'][0]['needs_review'])
        self.assertEqual(self.undo()[0],200)
        self.assertEqual(self.entries()[0]['words'][0]['group_reviews'],[])
        self.assertFalse(self.call('/api/lexeme-examples?id='+x['id'])[1]['items'][0]['needs_review'])

    def test_overlaps_revision_and_multi_root(self):
        e=self.seed('#pass([], (([am-gu-nas-os],[go-pres-dur-go]),), [])');d=self.get(e)
        saved=self.group(e,members=['0:host','3:host'],type='root',gloss='go')
        self.assertEqual([m['form'] for m in saved['body']['words'][0]['morphemes']],['am…os','gu','nas'])
        b=dict(kind='corpus',id=e['id'],revision=saved['revision'],word=0,action='save',type='circumfix',status='hypothesis',gloss='x',members=['0:host','2:host'])
        self.assertEqual(self.call('/api/segmentation-save',b)[0],400)
        b.update(members=['1:host','2:host'],revision=d['revision'])
        self.assertEqual(self.call('/api/segmentation-save',b)[0],400)
        b['revision']=saved['revision'];self.assertEqual(self.call('/api/segmentation-save',b)[0],200)
        now=self.get(e);g=now['body']['words'][0]['morph_groups'][0]
        self.assertEqual(self.call('/api/segmentation-save',dict(kind='corpus',id=e['id'],revision=now['revision'],word=0,action='delete',group_id=g['id']))[0],200)
        self.assertEqual(self.undo()[0],200);self.assertEqual(len(self.get(e)['body']['words'][0]['morph_groups']),2)

    def test_independent_links_preservation_exchange_and_backup(self):
        x=self.word();body=dict(ipa='test',words=[dict(form='we-amos-la',gloss='pst-go-pst')],targets=[dict(lexeme_id=x['id'])])
        code,e=self.call('/api/example-save',dict(body=body));self.assertEqual(code,200,e)
        d=self.group(e,'independent');key=d['body']['words'][0]['morphemes'][0]['key'];self.link(d,x,key,'independent')
        fresh=self.call('/api/dictionary-examples?id='+x['id'])[1][0]
        self.assertFalse(fresh['body']['targets'][1]['segmentation_review'])
        fresh['body']['words'][0]['form']='wu-amos-la'
        self.assertEqual(self.call('/api/example-save',fresh)[0],200)
        fresh=self.call('/api/dictionary-examples?id='+x['id'])[1][0]
        self.assertTrue(fresh['body']['targets'][1]['segmentation_review']);self.assertEqual(len(fresh['body']['words'][0]['group_reviews']),1)
        self.assertEqual(self.undo()[0],200)
        corpus_entry=self.seed('#pass([], (([so<l>ma],[home<nom.pl>]),), [])');cd=self.get(corpus_entry);self.link(cd,x,'0:infix:0')
        bundle=self.call('/api/export-language?language=ordos')[1]
        self.assertTrue(bundle['unit_segments'])
        lid=self.call('/api/save-language',dict(name='Copy',metadata={}))[1]['id']
        code,r=self.call('/api/import-language',dict(bundle=bundle,_language=lid));self.assertEqual(code,200,r)
        copied=self.call('/api/lexemes?language='+lid)[1]['items'][0]
        example=self.call('/api/dictionary-examples?id='+copied['id'])[1][0]
        self.assertFalse(example['body']['targets'][1]['segmentation_review'])
        self.assertEqual(example['body']['words'][0]['morphemes'][0]['form'],'we…la')
        refs=self.call('/api/lexeme-examples?id='+copied['id'])[1]
        self.assertEqual(refs['total'],1);self.assertEqual(refs['items'][0]['form'],'l')
        file=server.DB.parent/'backup.json';file.write_text(json.dumps(self.call('/api/backup')[1]),encoding='utf-8');destination=server.DB.parent/'restored.sqlite3';restore(file,destination)
        server.DB=destination
        self.assertEqual(self.call('/api/lexeme-examples?id='+copied['id'])[1]['total'],1)
        self.assertFalse(self.call('/api/dictionary-examples?id='+copied['id'])[1][0]['body']['targets'][1]['segmentation_review'])

    def test_removed_word_retains_orphan_analysis(self):
        e=self.seed('#pass([], (([we-amos-la],[pst-go-pst]),([x],[x])), [])');self.group(e)
        e=self.entries()[0];e['words']=e['words'][1:];e['notes']=''
        self.assertEqual(self.call('/api/save',e)[0],200)
        self.assertEqual(len(self.get(e)['body']['orphaned_morphology']),1)


if __name__=='__main__':unittest.main()
