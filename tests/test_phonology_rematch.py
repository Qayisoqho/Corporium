import copy,json,unittest
import phonology,server
import test_phonology as original


class PhonologyRematchTests(unittest.TestCase):
    for name in ('setUp','tearDown','call','settings','undo'):
        locals()[name]=getattr(original.PhonologyTests,name)

    def config(self):return self.call('/api/homophone-phonology?language=ordos')[1]
    def save(self,action,**body):
        code,result=self.call('/api/homophone-phonology-save',dict(action=action,token=self.config()['token'],**body))
        self.assertEqual(code,200,result);return result
    def confirm(self,reading,initials='m'):
        return self.save('classify',reading=reading,initials=initials,finals='a',tones='55')
    def actual(self,*readings):
        for n,reading in enumerate(readings):
            code,result=self.call('/api/morpheme-save',dict(form='m'+str(n),body=dict(readings=[reading],gloss='test')))
            self.assertEqual(code,200,result)
    def replace_final(self,ambiguous=False):
        values=original.inventory();values['finals']=[dict(id='new',label='new a',matches=['a'])]
        if ambiguous:values['finals'].append(dict(id='other',label='another a',matches=['a']))
        return self.settings(values)

    def test_rename_and_alias_order_preserve_confirmed_and_manual_exceptions(self):
        self.settings();self.confirm('ma55');self.confirm('manual-exception')
        values=original.inventory();values['finals'][0]['label']='新名称';values['tones'][0]['matches'].reverse()
        config=self.settings(values)
        for reading in ('ma55','manual-exception'):
            self.assertEqual(phonology.classify(reading,config)['state'],'confirmed')
        self.assertEqual(config['assignments']['ma55']['signature'],phonology.signature(config,config['assignments']['ma55']))

    def test_alias_changes_preserve_an_existing_choice_that_still_matches(self):
        self.settings();self.confirm('ma55')
        values=original.inventory();values['finals'][0]['matches']=['a','ɑ']
        config=self.settings(values)
        self.assertEqual(phonology.classify('ma55',config)['state'],'confirmed')
        values['initials'][0]['matches']=['m','mm'];config=self.settings(values)
        self.assertEqual(phonology.classify('ma55',config)['state'],'confirmed')

    def test_old_classifications_rematch_uniquely_and_can_be_confirmed_in_one_batch(self):
        self.actual('ma55','a55');self.settings();self.confirm('ma55');self.confirm('a55','zero')
        with server.connect(audit=False) as db:before=[tuple(r) for r in db.execute('SELECT id,body,revision FROM morphemes ORDER BY id')]
        config=self.replace_final()
        for reading in ('ma55','a55'):
            result=phonology.classify(reading,config)
            self.assertEqual(result['state'],'candidate');self.assertEqual(result['choice']['finals'],'new')
            self.assertEqual(result['previous_choice']['finals'],'a')
        table=self.call('/api/homophones?language=ordos&view=phonology')[1]
        self.assertEqual(table['pending_total'],2)
        confirmed=self.save('confirm_unique',all=True)
        self.assertTrue(all(phonology.classify(r,confirmed)['state']=='confirmed' for r in ('ma55','a55')))
        self.assertEqual(self.call('/api/homophones?language=ordos&view=phonology')[1]['pending_total'],0)
        with server.connect(audit=False) as db:self.assertEqual([tuple(r) for r in db.execute('SELECT id,body,revision FROM morphemes ORDER BY id')],before)

    def test_ambiguous_and_unmatched_old_assignments_still_require_manual_choice(self):
        self.actual('ma55');self.settings();self.confirm('ma55')
        config=self.replace_final(True);result=phonology.classify('ma55',config)
        self.assertEqual(result['state'],'ambiguous');self.assertEqual(len(result['candidates']),2)
        token=config['token'];code,_=self.call('/api/homophone-phonology-save',dict(action='confirm_unique',token=token,all=True))
        self.assertEqual(code,400);self.assertEqual(self.config()['token'],token)
        values=original.inventory();values['finals'][0]['matches']=['ɑ'];config=self.settings(values)
        self.assertEqual(phonology.classify('ma55',config)['state'],'stale')

    def test_bulk_is_atomic_and_checks_the_latest_inventory_token(self):
        self.actual('ma55','unknown');self.settings();self.confirm('ma55');self.confirm('unknown')
        old_token=self.config()['token'];self.replace_final();token=self.config()['token']
        for body in (dict(token=old_token,all=True),dict(token=token,readings=['ma55','unknown'])):
            code,_=self.call('/api/homophone-phonology-save',dict(action='confirm_unique',**body))
            self.assertEqual(code,400);self.assertEqual(self.config()['token'],token)
        config=self.save('confirm_unique',readings=['ma55'])
        self.assertEqual(phonology.classify('ma55',config)['state'],'confirmed')
        self.assertEqual(phonology.classify('unknown',config)['state'],'stale')

    def test_undo_and_redo_restore_settings_and_batch_confirmation_separately(self):
        self.actual('ma55');self.settings();self.confirm('ma55');self.replace_final();self.save('confirm_unique',all=True)
        self.assertEqual(phonology.classify('ma55',self.config())['choice']['finals'],'new')
        self.undo();self.assertEqual(phonology.classify('ma55',self.config())['state'],'candidate')
        self.undo();self.assertEqual(phonology.classify('ma55',self.config())['state'],'confirmed')
        self.assertEqual(phonology.classify('ma55',self.config())['choice']['finals'],'a')
        self.undo('redo');self.undo('redo')
        self.assertEqual(phonology.classify('ma55',self.config())['choice']['finals'],'new')

    def test_legacy_stale_signatures_are_recomputed_without_rewriting_saved_choices(self):
        config={**original.inventory(),'assignments':{}}
        choice=dict(initials='m',finals='a',tones='55')
        config['assignments']['ma55']={**choice,'signature':phonology.signature(config,choice)}
        saved=copy.deepcopy(config['assignments']);config['finals'][0]['id']='new'
        result=phonology.classify('ma55',config)
        self.assertEqual((result['state'],result['choice']['finals']),('candidate','new'))
        self.assertEqual(config['assignments'],saved)

    def test_batch_excludes_temporary_form_only_readings_and_unseen_saved_readings(self):
        self.actual('ma55');self.settings();self.confirm('ma55');self.confirm('a55','zero')
        code,result=self.call('/api/morpheme-save',dict(form='a55',body=dict(gloss='temporary')))
        self.assertEqual(code,200,result)
        self.replace_final();config=self.save('confirm_unique',all=True)
        self.assertEqual(phonology.classify('ma55',config)['state'],'confirmed')
        self.assertEqual(phonology.classify('a55',config)['state'],'candidate')
        self.assertEqual(config['assignments']['a55']['finals'],'a')

    def test_rematched_candidate_survives_language_exchange(self):
        self.actual('ma55');self.settings();self.confirm('ma55');self.replace_final()
        bundle=self.call('/api/export-language?language=ordos')[1]
        other=self.call('/api/save-language',dict(name='Copy',metadata={}))[1]['id']
        code,result=self.call('/api/import-language',dict(_language=other,bundle=bundle))
        self.assertEqual(code,200,result)
        config=self.call('/api/homophone-phonology?language='+other)[1]
        self.assertEqual(phonology.classify('ma55',config)['state'],'candidate')
        code,result=self.call('/api/homophone-phonology-save',dict(_language=other,action='confirm_unique',token=config['token'],all=True))
        self.assertEqual(code,200,result)
        self.assertEqual(phonology.classify('ma55',result)['state'],'confirmed')
        self.assertEqual(phonology.classify('ma55',self.config())['state'],'candidate')

    def test_rematch_reason_is_localized_in_group_and_pending_results(self):
        import ui_localization as ui
        reason='按当前音系清单重新匹配，结果唯一，可批量确认'
        data={'groups':[{'reading':'ma55','items':[],'classification':dict(state='candidate',reason=reason)}],
              'pending':[{'reading':'ma55','items':[],'classification':dict(state='candidate',reason=reason)}]}
        result=ui.present(data,'/api/homophones','en')
        for key in ('groups','pending'):
            self.assertIn('current sound inventory',result[key][0]['classification']['reason'])


if __name__=='__main__':unittest.main()
