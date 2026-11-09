"""Read-only audit of shared UI size tokens and their explicit exceptions."""
from pathlib import Path
import argparse,json,re

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'build/ui-style-audit');parser.add_argument('--check',action='store_true');args=parser.parse_args()
OUT=args.output.resolve();OUT.mkdir(parents=True,exist_ok=True)
CHROME=re.compile(r'#app-bar|#app-status|#brand-home|#brand-language|brand-language-picker|#home-|\.home-|\.startup-brand\b|#sidebar-toggle|#sidebar-resize|#workspace-toolbar|\.app-segmented|\.app-command|#ipa-keyboard|\.ipa-key')
CONTENT=re.compile(r'\.word-dictionary|\.judgment-mark|\.grammar-label|\.gloss\b|\.ipa\b|\.form\b|\.translation\b|\.morpheme-form|\.dictionary-wordform|\.morph-form-view|\.morph-evidence|\.inline-words|\.inline-ipa|\.inline-gloss|\.inline-translation|\.survey-rich-input|\.analysis-notes|\.sentence-notes|\.example-notes(?!.*summary)|\.homophone-entry|\.hp-cell-title|#hp-reading|\.font-preview|\.language-font-preview|\.tl-block|\.tl-ruler|\.tl-wave|\.tl-region|\.tl-canvas|\.tl-selection-label|\.tl-mark|\.tl-timecode|#lexeme-headword|#morpheme-form-value|\.sense-short|\.morpheme-sense-gloss|data-ws=["\']?form')
ICON=re.compile(r'::before|::after|\bsvg\b|\.close\b|icon-grid|pan-row|sort-handle|row-grip|resize|\.tl-toggle|\.font-stack-grip')
UI=re.compile(r'\bbutton\b|\binput\b|\bselect\b|\btextarea\b|\blabel\b|\bsummary\b|\bdialog\b|pagination|homophone|#hp-|-(?:tools|help|hint|form|controls|filters|actions|status|notice|error|heading|note|empty|count|label|description|summary)\b|settings|metadata|dictionary-filter|font-(?:stack|catalog)|fieldwork|startup|\.empty\b|\.muted\b')
HELP=re.compile(r'\bsmall\b|-(?:help|hint|note|notice|error|status|empty|count|path|description)\b|\.empty\b|\.muted\b|\.tl-muted\b')
CONTROL=re.compile(r'(?:^|[\s,(:>])(?:button|input|select|textarea)\b')
NATIVE=re.compile(r'type\s*[=~]\s*["\']?(?:checkbox|radio|range|color|file)|\[hidden\]')
SIZE=re.compile(r'^([\d.]+)(px|rem|em)?(!important)?$')
records=[]
for path in sorted([*(ROOT/'web').glob('*.css'),*(ROOT/'web').glob('*.html')]):
    if path.name=='ui-standards.css':continue
    original=path.read_text(encoding='utf-8')
    def rule(match):
        selector,body=match.groups()
        clean=re.sub(r'/\*.*?\*/','',selector,flags=re.S).strip()
        positive=re.sub(r':not\([^()]*\)','',clean)
        props=dict(re.findall(r'([\w-]+)\s*:\s*([^;]+)',body))
        has_font=any(k in props for k in ('font-size','font'))
        is_ui=bool(UI.search(clean) or re.search(r'code-time-reference|example-group-pick|survey-card|survey-root-drop|survey-search|about-version|legal-notices-(?:section|intro|choice)|organize-bar|undo-panel|language-details|lex-tag|word-structure-editor|grammar-table|ws-parts-view|paradigm-(?:layout-toggle|control-field|quick|independent-badge|inheritance)|sentence-audio-choice|slot-drag-toggle|workbench-preferences|#subtitle|docx-slot|dr-conditions|morpheme-source-missing|sentence-search-dock|workspace-loading|morph-color-bottom|replace-issues|app-command-palette|app-command-results|grammar-types',clean) or re.search(r'text-filter|analysis-|dictionary-|\.lx-|quick-|homophone|#hp-|(?:#|\.)tl-|playback-volume|font-candidate|reading-index|batch-|example-group-filter|example-source-number|sentence-number|entry-head|result-bar|\.filters|\.warning|\.language-panel|\.language-badge|\.font-panel|semantic-memberships|morpheme-meta|morpheme-detail|morpheme-list|sense-synonyms|sense-identity|sense-kind|lexeme-entry-type|lexeme-list-pos|object-media-speakers|object-media-thumbs figcaption|dialogue-|code-overview|\.eyebrow|\.workbench-(?:preferences|language-options|document-info|batch)|\.workbench-search-options|#workbench-tool-toggle|#text-reading-target|#corporium-message-body|#intake-grammar|#morph-color-theme|#auto-candidate-selection',clean));is_control=bool(CONTROL.search(positive))
        reason='interface'
        if CHROME.search(clean):
            reason='interface text / preserved chrome geometry' if re.search(r'#workspace-toolbar|\.app-segmented|#app-command|#brand-language-menu|#app-bar.*(?:workspace-tabs|management-open)',clean) and not re.search(r'font-size:\s*0(?:[;}]|$)|\bsvg\b|::before|::after',body) else 'structural chrome / keyboard'
        elif re.search(r'\.lexeme-title|\.lexeme-list-item\s+strong|\.morpheme-detail-head\s+h2|#morpheme-detail>h2|\.tl-tick|\.tl-time-label|\.code-span|\.survey-rich\b|\.survey-search-extra|\.sense-addition-preview|\.paradigm-gloss-preview|\.morph-color-preview|\.dictionary-layer-value|\.ws-writing-view|\.orthography-text|\.legal-notices-text|(?:^|[\s,(:])(?:sub|sup)\b',positive):reason='research text / configured font'
        elif CONTENT.search(positive) or re.search(r'\.font-stack-preview\s+p|(?:\.language-body|\.editable-example).*\b(?:input|textarea)\b|\.ws-component.*\binput\b|\.ws-registry-form',positive) or re.search(r'font(?:-family)?:[^;]*(?:--(?:annotation|ipa|gloss|translation|inline-row|example-font)|Junicode|IPAPAN)',body):reason='research text / configured font'
        elif ICON.search(clean):reason='icon / grip geometry'
        elif re.search(r'(?:^|[\s,>])(?:pre|code)\b',clean):reason='document / source text'
        elif not is_ui:reason='non-control content / layout'
        changes={}
        if reason in ('interface','icon / grip geometry','interface text / preserved chrome geometry'):
            def declaration(d):
                key,value=d.groups();value=value.strip();new=value
                if reason=='interface text / preserved chrome geometry' and key not in ('font-size','font'):return d[0]
                size=SIZE.fullmatch(value)
                native_check=bool(re.search(r'type\s*=\s*[\"\']?(?:checkbox|radio)|multipart-toggle.*\binput\b',positive))
                protected_icon=reason=='icon / grip geometry'
                if native_check:
                    if key in ('height','width') and size and 0<float(size[1])*(1 if size[2]=='px' else 16)<=24:new='var(--ui-check-size)'
                elif protected_icon:
                    if key in ('height','min-height') and is_control and size and 24<=float(size[1])*(1 if size[2]=='px' else 16)<=48:new='var(--ui-field-height)'+(size[3] or '')
                elif key=='font-size' and size:
                    number=float(size[1]);px=number if size[2]=='px' else number*16
                    if 0<px<=18:
                        heading=bool(re.search(r'\bh[23]\b',clean))
                        token='--ui-heading-size' if heading else '--ui-help-size' if (HELP.search(clean) or re.search(r'list-pos|sense-kind|entry-type|sentence-number|example-source-number|language-badge|source-info|media-details|figcaption|\.tl-muted|\.tl-job|wave-usage|wave-state',clean)) and not is_control else '--ui-text-size'
                        new='var('+token+')'+(size[3] or '')
                elif key=='font' and not value.startswith('inherit'):
                    found=re.search(r'(?<![\w-])([\d.]+)(px|rem|em)(?:/([\d.]+))?',value)
                    if found and 0<float(found[1])*(1 if found[2]=='px' else 16)<=18:
                        new=value[:found.start()]+'var(--ui-text-size)'+('/var(--ui-text-leading)' if found[3] else '')+value[found.end():]
                elif key in ('height','min-height') and is_control and not NATIVE.search(positive) and size:
                    number=float(size[1]);px=number if size[2]=='px' else number*16
                    if 0<=px<=48:new='var(--ui-field-height)'+(size[3] or '')
                elif key=='line-height' and is_control and not NATIVE.search(positive) and re.fullmatch(r'[\d.]+(?:px|rem|em)?',value):
                    new='var(--ui-text-leading)'
                elif key=='padding' and is_control and not NATIVE.search(positive) and re.fullmatch(r'[\d.pxrem% ]+',value) and re.match(r'(?!0(?:\s|$))',value):
                    new='var(--ui-control-padding)'
                if new!=value:changes[key]=dict(before=value,after=new)
                return key+':'+new if new!=value else d[0]
            body=re.sub(r'(?<![\w-])(font-size|font|height|min-height|width|line-height|padding)\s*:\s*([^;]+)',declaration,body)
        if has_font or changes:
            records.append(dict(file=path.relative_to(ROOT).as_posix(),selector=clean,classification=reason,changes=changes))
        return selector+'{'+body+'}'
    if path.suffix=='.html':
        result=re.sub(r'(<style[^>]*>)(.*?)(</style>)',lambda m:m[1]+re.sub(r'([^{}]+)\{([^{}]*)\}',rule,m[2])+m[3],original,flags=re.S)
    else:result=re.sub(r'([^{}]+)\{([^{}]*)\}',rule,original)
(OUT/'review.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
changed=[r for r in records if r['changes']]
print('Review:',len(records),'rules;',len(changed),'changed rules;',sum(len(r['changes']) for r in changed),'declarations;',len(set(r['file'] for r in changed)),'files')
for name in sorted(set(r['file'] for r in changed)):
    rows=[r for r in changed if r['file']==name]
    print(name,len(rows))

raise SystemExit(1 if args.check and changed else 0)
