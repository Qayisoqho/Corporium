"""Deterministic fictional inputs; no personal corpus files are required."""
def typ_source(count):
    pairs = [
        '([a-b],[root-NOM]),([na],[1SG])',
        '([c=d],[word=PART]),([。],[])',
        '([so<l>ma],[home<PL>]),([x],[meaning])',
        '([je~jepasu],[RED~go]),([ə],[NEG])',
        '([mülü],[词]),([uul],[caus#sub[PQ]])',
        '([we-amos-la],[PST-go-PST]),([«],[«])',
    ]
    return '\n'.join(f'#pass([synthetic {i} əː], ({pairs[i % len(pairs)]}), [合成译文 {i}])' for i in range(count))

def excel_without_translation():
    import excel_exchange
    rows = [['ID', 'Group', 'Position', 'IPA', 'Morph', 'Gloss', 'Notes']]
    for i in range(16):
        rows += [[str(i), '', '1', f'synthetic{i} ipa', 'a-b', 'root-NOM', '合成备注'],
                 [str(i), '', '2', 'na', 'na', '1SG', ''], []]
    return excel_exchange.workbook([('Synthetic', rows)])
