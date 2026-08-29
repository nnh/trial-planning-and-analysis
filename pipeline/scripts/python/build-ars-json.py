# build-ars-json.py
#
# ARD（ard_cards.csv）から CDISC ARS v1.0 の ReportingEvent を JSON で組み立てる。
#
# ARS は解析メタデータと結果を1つの ReportingEvent に入れ子で持つ。ARD が独立した
# ファイルではなく、Analysis.results として ReportingEvent の一部になる。
#
#   ReportingEvent
#     ├ mainListOfContents  … Output の並び（必須）
#     ├ analysisSets        … AS-FAS 等
#     ├ dataSubsets         … SS-PN 等
#     ├ analysisGroupings   … SUBTYPE 等
#     ├ methods             … Mth-KM 等（Operation を子に持つ）
#     ├ analyses            … An-5.4.1-01 等（results に OperationResult を持つ）
#     └ outputs             … Out-5.4.1 等
#
# 必須スロットは ReportingEvent が id・name・mainListOfContents、Analysis が
# id・name・reason・purpose・methodId、OperationResult が operationId。
# formattedValue は持たない（整形は表示層が持つ。ars-migration-plan.md の決定）。
#
# 必須スロットは記憶や要約で決めず、標準が公開しているスキーマから写す。写しは
# docs/metadata/external/ars-v1-0.schema.json（LinkML モデルから生成されたもの）で、
# 検証は scripts/check-ars-json.py が行う。2026-08-29 に自前の必須スロット検査だけで
# 準拠と判断していたところ、スキーマにかけたら1,319件の違反が出た。自前の検査は
# 書いた分しか見ない。
#
# 位置づけ。ReportingEvent はパイプラインの部品ではなく、末端から枝分かれする成果物である。
# ARD はパイプラインの一部として残り、図表の材料であり突合の主軸でもある。SAS は ard.ard
# から、R は ard_cards.csv から図表を描き続け、この JSON を読み返すことはない。読み手は
# 解析の由来を機械可読な形で受け取る側と、ARS を入力とするツールである。
#
# 元になるファイル
#   ard_cards.csv（SAS 系 or R 系）      結果値。Analysis.results になる
#   docs/metadata/analysis-purpose.csv   purpose と reason。Analysis の必須スロット
#   docs/metadata/tlf-index.csv          図表の宣言。Output と mainListOfContents の並び
#   docs/metadata/label-catalog.csv      図表の表題。Output.name
#
# 使い方
#   python scripts/build-ars-json.py                    ... SAS系の ARD から作る
#   python scripts/build-ars-json.py --system r         ... R系の ARD から作る
#   python scripts/build-ars-json.py --out <path>       ... 出力先を指定
import sys, os, csv, json, argparse, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_csv(path, enc='utf-8-sig'):
    with open(path, encoding=enc, newline='') as f:
        return list(csv.DictReader(f))


def label_map():
    """図表の表題。Output.name に使う"""
    p = os.path.join(REPO, 'docs', 'metadata', 'label-catalog.csv')
    out = {}
    for r in read_csv(p):
        if r.get('kind') == 'title' and r.get('key'):
            out[r['key']] = (r.get('label_en') or r.get('label_ja') or r['key']).strip()
    return out


def purpose_map():
    """Output ごとの purpose と reason。Analysis の必須スロット"""
    p = os.path.join(REPO, 'docs', 'metadata', 'analysis-purpose.csv')
    return {r['output_id']: r for r in read_csv(p)}


def tlf_index():
    """図表の宣言。Output と Analysis の対応と並び順を持つ"""
    p = os.path.join(REPO, 'docs', 'metadata', 'tlf-index.csv')
    return read_csv(p)


def build(cards, titles, purposes, tlf):
    # --- 参照される要素を ARD の実値から集める ---
    sets, subsets, groupings, methods, ops = set(), set(), set(), set(), set()
    per_analysis = collections.OrderedDict()
    for r in cards:
        aid = r['analysis_id']
        if aid not in per_analysis:
            per_analysis[aid] = {'rows': [], 'meta': r}
        per_analysis[aid]['rows'].append(r)
        if r.get('analysis_set'):
            sets.add(r['analysis_set'])
        if r.get('data_subset'):
            subsets.add(r['data_subset'])
        if r.get('group1'):
            groupings.add(r['group1'])
        if r.get('method_id'):
            methods.add(r['method_id'])
        if r.get('operation_id'):
            ops.add((r['method_id'], r['operation_id'], r.get('stat_label') or ''))

    # --- AnalysisMethod と、その子の Operation ---
    by_method = collections.defaultdict(list)
    for mid, oid, lbl in sorted(ops):
        by_method[mid].append({'id': oid, 'name': oid.split('.', 1)[-1], 'label': lbl,
                               'order': len(by_method[mid]) + 1})
    method_objs = [{'id': m, 'name': m, 'operations': by_method[m]} for m in sorted(methods)]

    # --- Analysis ---
    analyses = []
    for aid, d in per_analysis.items():
        meta = d['meta']
        oid = meta.get('output_id') or ''
        pu = purposes.get(oid, {})
        a = {
            'id': aid,
            'name': aid,
            'reason': {'controlledTerm': pu.get('reason', 'SPECIFIED IN SAP')},
            'purpose': {'controlledTerm': pu.get('purpose', 'EXPLORATORY OUTCOME MEASURE')},
            'methodId': meta.get('method_id') or '',
        }
        if meta.get('analysis_set'):
            a['analysisSetId'] = meta['analysis_set']
        if meta.get('data_subset'):
            a['dataSubsetId'] = meta['data_subset']
        if meta.get('src_data'):
            a['dataset'] = meta['src_data']
        if meta.get('variable'):
            a['variable'] = meta['variable']
        if meta.get('group1'):
            # resultsByGroup は OrderedGroupingFactor の必須スロット。結果値を群ごとに
            # 分けて報告するかどうかを表す。本試験の ARD は群ごとに行を分けており、
            # その群は下の resultGroups に現れるので真になる
            a['orderedGroupings'] = [{'order': 1, 'groupingId': meta['group1'],
                                      'resultsByGroup': True}]
        if meta.get('output_id'):
            a['categoryIds'] = [meta['output_id']]

        results = []
        for r in d['rows']:
            # rawValue は丸めを適用しない値。数値と文字のどちらかが入る
            raw = r.get('stat_num') if r.get('stat_type') == 'num' else r.get('stat_char')
            res = {'operationId': r.get('operation_id') or ''}
            groups = []
            if r.get('group1') and r.get('group1_level'):
                groups.append({'groupingId': r['group1'], 'groupId': r['group1_level']})
            if r.get('variable_level'):
                # 変数の水準も結果を分ける軸なので resultGroups で表す
                groups.append({'groupingId': r.get('variable') or 'VARIABLE',
                               'groupId': r['variable_level']})
            if groups:
                res['resultGroups'] = groups
            if raw not in (None, ''):
                res['rawValue'] = str(raw)
            results.append(res)
        a['results'] = results
        analyses.append(a)

    # --- Output（報告する図表）。宣言の lblid が1件の図表に対応する ---
    # ARD の output_id（Out-5.4.1 等）は SAP の節に対応する解析の束ねで、報告する図表とは
    # 粒度が違う。1つの Out- が複数の図表を生む（表 5.4.9 が4表だった頃の名残もある）。
    # ARS の Output は「報告される結果の単位」なので図表の側を採り、Out- は
    # AnalysisOutputCategorization（実装者定義の分類）として持つ。
    seen, outputs, contents = set(), [], []
    lbl_to_analyses = collections.defaultdict(list)
    for row in tlf:
        lbl = (row.get('lblid') or '').strip()
        if not lbl or lbl in seen:
            continue
        seen.add(lbl)
        # displays は Output の必須スロットで、OrderedDisplay（order と display の組）の
        # 並び。本試験は1つの図表が1つの表示なので1件だけ持つ
        nm = titles.get(lbl, lbl)
        outputs.append({
            'id': lbl, 'name': nm,
            'displays': [{'order': 1, 'display': {'id': lbl + '-D1', 'name': nm,
                                                  'displayTitle': nm}}],
        })
        aid = (row.get('analysis_id') or '').strip()
        if aid:
            lbl_to_analyses[lbl].append(aid)

    # mainListOfContents.contentsList は NestedList（listItems を持つ入れ子）であって
    # 項目の配列ではない。各項目は OrderedListItem で level・order・name が必須。
    # 本試験は入れ子にせず、図表を宣言の順（章番号順）に1階層で並べる
    for i, o in enumerate(outputs, 1):
        contents.append({'level': 1, 'order': i, 'name': o['name'], 'outputId': o['id']})

    # SAP の節ごとの分類。各解析が categoryIds でここを指す
    cats = sorted({r.get('output_id') for r in cards if r.get('output_id')})
    categorization = [{
        'id': 'CAT-SAP-SECTION',
        'label': 'SAP section',
        'categories': [{'id': c, 'label': titles.get(c, c)} for c in cats],
    }]

    return {
        # 試験固有の値は docs/metadata/trial.json だけが持つ（scripts/boxpath.py が引く）
        'id': 'RE-' + boxpath.trial_id(),
        'name': boxpath.trial_id() + ' Reporting Event',
        'description': 'Analyses and outputs for the clinical study report',
        'mainListOfContents': {'name': 'Main list of contents',
                               'contentsList': {'listItems': contents}},
        'analysisOutputCategorizations': categorization,
        # AnalysisSet と DataSubset は level と order が必須（入れ子にできる定義のため）。
        # 本試験はどちらも入れ子を持たないので level は 1 で、order は識別子の順に振る
        'analysisSets': [{'id': s, 'name': s, 'level': 1, 'order': i}
                         for i, s in enumerate(sorted(sets), 1)],
        'dataSubsets': [{'id': s, 'name': s, 'level': 1, 'order': i}
                        for i, s in enumerate(sorted(subsets), 1)],
        # dataDriven は GroupingFactor の必須スロットで、群がメタデータに列挙されて
        # いるか、データの値から決まるかを表す。ここは群を列挙せず ADaM の変数名だけを
        # 持つので真になる。群を列挙する形へ進めるなら偽に変える
        'analysisGroupings': [{'id': g, 'name': g, 'dataDriven': True}
                              for g in sorted(groupings)],
        'methods': method_objs,
        'analyses': analyses,
        'outputs': outputs,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--system', choices=['sas', 'r'], default='sas')
    ap.add_argument('--out')
    a = ap.parse_args()

    box = boxpath.trial_dir()
    src = (os.path.join(box, 'datasets', 'sas', 'ard', 'ard_cards.csv') if a.system == 'sas'
           else os.path.join(box, 'datasets', 'r', 'ard', 'ard_cards_r.csv'))
    if not os.path.isfile(src):
        sys.exit(f'ARD が無い: {src}')

    out = a.out or os.path.join(box, 'datasets', a.system, 'ard',
                                f'reporting-event-{a.system}.json')
    cards = read_csv(src)
    re_obj = build(cards, label_map(), purpose_map(), tlf_index())

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(re_obj, f, ensure_ascii=False, indent=2)

    n_res = sum(len(x['results']) for x in re_obj['analyses'])
    print(f'{src} を読んだ（{len(cards):,} 行）')
    print(f'{out} を書いた')
    print(f'  解析 {len(re_obj["analyses"]):,} / 結果値 {n_res:,} / 図表 {len(re_obj["outputs"])}')
    print(f'  集団 {len(re_obj["analysisSets"])} / サブセット {len(re_obj["dataSubsets"])} '
          f'/ 群 {len(re_obj["analysisGroupings"])} / 手法 {len(re_obj["methods"])}')


if __name__ == '__main__':
    main()
