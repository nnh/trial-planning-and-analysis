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
# formattedValue は持たない（整形は表示層が持つ。ard-double-coding-spec.md の
# 「ReportingEvent の位置づけ」）。
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
#   docs/metadata/analysis-purpose.csv   purpose と reason。Analysis の必須スロット。
#                                        output_id の行が既定、analysis_id の行が上書き
#   docs/metadata/tlf-index.csv          図表の宣言。Output と mainListOfContents の並び
#   docs/metadata/label-catalog.csv      図表の表題。Output.name と水準の表示名
#   docs/metadata/level-sets.csv         事前規定の水準集合。GroupingFactor になる
#
# 使い方
#   python scripts/build-ars-json.py                    ... SAS系の ARD から作る
#   python scripts/build-ars-json.py --system r         ... R系の ARD から作る
#   python scripts/build-ars-json.py --out <path>       ... 出力先を指定
import sys, os, re, csv, json, argparse, collections
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


def level_label_map():
    """水準の表示名（label-catalog.csv の kind=level）。Group.label に使う。

    表示文言の正本はこの CSV だけなので、宣言をもう1か所へ写さない。宣言の無い水準は
    識別子をそのまま label にする（label-catalog.csv 側の欠落は表示の判断であって、
    ReportingEvent の組み立てを止める理由にはならない）。
    """
    p = os.path.join(REPO, 'docs', 'metadata', 'label-catalog.csv')
    out = {}
    for r in read_csv(p):
        if r.get('kind') == 'level' and r.get('key'):
            v = (r.get('label_en') or '').strip()
            if v:
                out[r['key'].strip()] = v
    return out


def read_level_sets():
    """事前規定の水準集合（docs/metadata/level-sets.csv）。

    ARD の `variable_level` には、実装が集合として列挙した事前規定の水準と、データに
    現れた値をそのまま採った水準が同居していた。前者を ARS の事前規定の GroupingFactor
    として分けるため、ARD が `level_set` 列で集合の識別子を持ち、ここでその集合の水準を
    読む（C3-002。2026-09-05）。

    水準の並びは `display_order`（表示の順）を採り、無ければ `impl_order`（実装が列挙する
    順）で埋める。ARS の Group.order は表示の順序を表すスロットだからである。
    """
    p = os.path.join(REPO, 'docs', 'metadata', 'level-sets.csv')
    if not os.path.isfile(p):
        # 空で返すと事前規定の水準がすべてデータ由来へ落ち、分けた意味が無くなる
        raise SystemExit(f'ERROR: 水準集合の定義が無い: {p}')
    out = collections.OrderedDict()
    for r in read_csv(p):
        sid = (r.get('set_id') or '').strip()
        lv = (r.get('level') or '').strip()
        if not sid or not lv:
            continue
        io = (r.get('impl_order') or '').strip()
        do = (r.get('display_order') or '').strip()
        out.setdefault(sid, []).append((int(do or io), int(io or 0), lv))
    for sid in out:
        out[sid].sort()
    return out


def purpose_map():
    """purpose と reason。Analysis の必須スロットで、標準は解析ごとに値を持つ形だけを
    用意している（Output にも同名のスロットは無い）。

    同じ Output に属する解析は多くが同じ値を採るので、`output_id` の行を既定として
    配り、値が違う解析だけ `analysis_id` の行で上書きする。継承は標準の仕掛けではなく
    ここの規約なので、上書きが効いた件数を実行時に報告して、既定が黙って行き渡って
    いる状態と区別が付くようにする（C2-145）。
    """
    p = os.path.join(REPO, 'docs', 'metadata', 'analysis-purpose.csv')
    rows = read_csv(p)
    by_out = {r['output_id']: r for r in rows if not r.get('analysis_id')}
    by_an = {r['analysis_id']: r for r in rows if r.get('analysis_id')}
    return by_out, by_an


def tlf_index():
    """図表の宣言。Output と Analysis の対応と並び順を持つ"""
    p = os.path.join(REPO, 'docs', 'metadata', 'tlf-index.csv')
    return read_csv(p)


def read_reference_docs():
    """ReportingEvent が指す文書（docs/metadata/reference-documents.csv）。

    結果値だけを渡されても、集団の条件・手法・入力データの所在が分からなければ第三者は
    解析を再実行できない。ARS は ReferenceDocument でこれを持つ場所を用意しているので、
    納品パッケージ内の位置とともに収める（C2-162）。

    `for_reason` 列は、その文書を根拠とする `Analysis.reason` の値を持つ。reason が
    「いつ計画されたか」を述べるだけでは、受領者はその主張を裏づける文書へ辿れない。
    reason から根拠文書を引いて Analysis の documentRefs にする（C3-006）。文書の一覧も
    対応も CSV が持ち、ここには写さない。
    """
    p = os.path.join(REPO, 'docs', 'metadata', 'reference-documents.csv')
    if not os.path.isfile(p):
        return [], {}
    out, by_reason = [], collections.defaultdict(list)
    for r in read_csv(p):
        d = {'id': r['id'], 'name': r['name']}
        for k in ('label', 'location', 'description'):
            if r.get(k):
                d[k] = r[k]
        out.append(d)
        if r.get('for_reason'):
            by_reason[r['for_reason']].append(r['id'])
    return out, dict(by_reason)


def read_method_code(system):
    """手法ごとの実装（docs/metadata/method-code.csv）。

    AnalysisMethod の codeTemplate は、その手法をどう計算したかを機械可読に持つ場所である。
    ここが空だと「Mth-KM」という名前だけが残り、信頼区間の方式も打ち切りの規則も
    ReportingEvent からは辿れない（C2-162）。

    codeTemplate が指すのは「その結果を実際に出したコード」なので、系統ごとに中身が違う。
    `system` 列で分け、組み立てる系統の行だけを読む。2026-08-31 まで R の行を両系統へ
    配っていたため、SAS の ReportingEvent が R の言語名・R のプログラムのパス・R 一式を
    指す文書を生成コードとして示していた（C3-013）。
    """
    p = os.path.join(REPO, 'docs', 'metadata', 'method-code.csv')
    if not os.path.isfile(p):
        return {}
    return {r['method_id']: r for r in read_csv(p) if r.get('system') == system}


def grouping_obj(gid, grp, lvlabels):
    """GroupingFactor を1件組む。定義は docs/metadata/analysis-grouping.csv が持つ（C2-142）

    定義の無い因子は build が先に落とす。ここで「分からないからデータ由来」と既定へ
    落とすと、事前規定の群が黙ってデータ由来を名乗って出ていく（C3-001）。

    表示名は label-catalog.csv（kind=level）から引く。宣言の CSV にも表示名の列を置くと
    同じ文言が2か所になり、片方だけ改訂したときに図表と解析メタデータが違う名前を述べる。
    水準集合（levelset_obj）も同じ台を引いており、群と水準で引き方を変えない。
    """
    g = grp[gid]
    o = {'id': gid, 'name': gid, 'dataDriven': g['data_driven']}
    if g['dataset']:
        o['groupingDataset'] = g['dataset']
    if g['variable']:
        o['groupingVariable'] = g['variable']
    if not g['data_driven'] and g['groups']:
        o['groups'] = [{'id': r['group_id'], 'name': r['group_id'],
                        'label': lvlabels.get(r['group_id'], r['group_id']),
                        'level': 1, 'order': int(r['order'])} for r in g['groups']]
    return o

def levelset_obj(sid, levels, lvlabels):
    """事前規定の水準集合を GroupingFactor 1件にする（C3-002。2026-09-05）。

    群を作るのは ARD の `variable_level` 列で、その水準が計画で決まっているものである。
    `dataDriven` は偽で、水準は `groups` に並び、結果は `groupId` でそれを指す。水準の
    正本は level-sets.csv、表示名の正本は label-catalog.csv で、どちらもここへ写さない。
    """
    return {
        'id': sid, 'name': sid, 'dataDriven': False,
        # 他の因子が ADaM のデータセットと変数を置くのに合わせる。水準の出どころは ARD の
        # variable_level 列なので、VARIABLE-LEVEL と同じ台を指す
        'groupingDataset': 'ARD', 'groupingVariable': 'variable_level',
        'groups': [{'id': lv, 'name': lv, 'label': lvlabels.get(lv, lv),
                    'level': 1, 'order': i}
                   for i, (_, _, lv) in enumerate(levels, 1)],
    }


def read_groupings():
    """群の定義（docs/metadata/analysis-grouping.csv）。

    ARS の `dataDriven` は、群が事前に規定されたもの（false）か、変数の相異なるデータ値から
    得られたもの（true）かを表す。実装が群を列挙したかどうかではない。事前規定なら `groups`
    に水準を並べ、結果は `groupId` でそれを指す。データ由来なら `groups` を持たず、結果は
    `groupValue` で実際の値を指す（C2-142・C2-140）。

    多くの因子は計画で決まる（評価時点・治療相など）。実データに現れた値で群が決まるのは、
    事前に水準を列挙できないものに限られる。どちらであるかは試験ごとに違うので、この CSV の
    data_driven が持ち、コードは既定を置かない。

    `data_driven` は Y か N のどちらかで、同じ因子の行はすべて同じ値・同じ dataset・
    同じ variable を持つ。空欄・誤記・因子内の食い違いを黙って偽と読むと、データ由来の
    群が事前規定を名乗る（逆も起きる）。読めないものは組み立てを止める（C3-001）。
    """
    p = os.path.join(REPO, 'docs', 'metadata', 'analysis-grouping.csv')
    if not os.path.isfile(p):
        # 空で返すと全因子が定義なしになり、データ由来への既定落ちを廃した意味が無くなる
        raise SystemExit(f'ERROR: 群の定義が無い: {p}')
    out, err = {}, []
    for i, r in enumerate(read_csv(p), 2):   # CSV の行番号。1行目は見出し
        gid = r['grouping_id']
        # 水準集合は level-sets.csv が正本で、この CSV には入れない。入れると全行を群の
        # 因子として読むこの関数が、水準集合を group1 の軸として拾う（2026-09-03 に
        # 混ぜなかった理由がこれである）。種別は LS_ の名前空間で分かれているので、
        # その名前で来た行はここで止める。黙って群にしない
        if gid.startswith('LS_'):
            err.append(f'{i} 行目 {gid}: 水準集合は docs/metadata/level-sets.csv が正本で、'
                       'この CSV には置かない')
            continue
        if r['data_driven'] not in ('Y', 'N'):
            err.append(f'{i} 行目 {gid}: data_driven が Y でも N でもない（{r["data_driven"]!r}）')
            continue
        now = (r['data_driven'] == 'Y', r.get('dataset') or '', r.get('variable') or '')
        g = out.setdefault(gid, {'data_driven': now[0], 'dataset': now[1],
                                 'variable': now[2], 'groups': []})
        if now != (g['data_driven'], g['dataset'], g['variable']):
            err.append(f'{i} 行目 {gid}: 同じ因子の他の行と '
                       f'data_driven・dataset・variable が食い違う')
        if r.get('group_id'):
            g['groups'].append(r)
    if err:
        raise SystemExit('ERROR: analysis-grouping.csv の不備\n  ' + '\n  '.join(err))
    return out


def read_conditions():
    """解析対象集団・データサブセットの選択条件（docs/validation/acceptance/analysis-set-condition.csv）。

    ARS の AnalysisSet・DataSubset は、対象をどう選ぶかを Condition で持つ。ここが空だと
    識別子と名前だけの殻になり、第三者は誰を数えたのかを ReportingEvent から辿れない
    （docs/validation/records/codex-review-2-ledger.md の C2-146）。
    単一の条件で表せないものは条件を空にし、note を label に載せる。
    """
    p = os.path.join(REPO, 'docs', 'validation', 'acceptance', 'analysis-set-condition.csv')
    if not os.path.isfile(p):
        # 空で返すと Condition の無い殻の AnalysisSet が並び、C2-146 で塞いだ穴が
        # 黙って開く。読めないときは組み立てを止める（2026-08-31）
        raise SystemExit(f'ERROR: 受入基準が無い: {p}')
    out = {}
    for r in read_csv(p):
        out[r['id']] = r
    return out


def set_obj(sid, i, cond):
    """AnalysisSet / DataSubset の1件を組む"""
    o = {'id': sid, 'name': sid, 'level': 1, 'order': i}
    c = cond.get(sid)
    if not c:
        return o
    if c.get('note'):
        o['label'] = c['note']
    if c.get('variable') and c.get('comparator'):
        o['condition'] = {
            'dataset': c.get('dataset') or 'ADSL',
            'variable': c['variable'],
            'comparator': c['comparator'],
        }
        if c.get('value'):
            o['condition']['value'] = [c['value']]
    return o


def build(cards, titles, purposes, tlf, cond=None, refdocs=None, mcode=None,
          grp=None, dref=None, lsets=None, lvlabels=None):
    # --- 参照される要素を ARD の実値から集める ---
    sets, subsets, groupings, methods, ops = set(), set(), set(), set(), set()
    used_ls = collections.defaultdict(set)   # 使われた水準集合 → 現れた水準
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
        if r.get('level_set'):
            used_ls[r['level_set']].add(r.get('variable_level') or '')
        if r.get('method_id'):
            methods.add(r['method_id'])
        if r.get('operation_id'):
            ops.add((r['method_id'], r['operation_id'], r.get('stat_label') or ''))

    # ARD が使う因子には analysis-grouping.csv に定義がある。定義の無い因子を
    # データ由来として出すと、群がどこで決まったかを確かめないまま真を名乗る（C3-001）
    grp = grp or {}
    undef = sorted(g for g in groupings if g not in grp)
    if undef:
        sys.exit('analysis-grouping.csv に定義の無い群の因子を ARD が使っている: '
                 + '、'.join(undef))

    # ARD が名指しした水準集合には level-sets.csv に宣言がある。宣言と実装が食い違えば
    # 組み立てを止める。この検査があるから、ARS 側で「事前規定の水準」と名乗れる
    # （宣言が実装の事実を言い直してよいのは、突き合わせる検査を付けられるときだけ。
    #  docs/work-logs/20260903-work-log.md「判断の基準を決めたこと」）
    lsets = lsets or {}
    lserr = []
    for sid in sorted(used_ls):
        if sid not in lsets:
            lserr.append(f'{sid}: ARD が名指ししているが level-sets.csv に無い')
            continue
        decl = {lv for _, _, lv in lsets[sid]}
        stray = sorted(x for x in used_ls[sid] if x and x not in decl)
        if stray:
            lserr.append(f'{sid}: 宣言に無い水準が ARD に出ている: '
                         + '、'.join(stray))
        if '' in used_ls[sid]:
            lserr.append(f'{sid}: level_set があるのに variable_level が空の行がある')
    # 因子の名前空間が重なると、結果行がどちらの因子を指すのかが決まらない
    both = sorted(set(used_ls) & set(grp))
    if both:
        lserr.append('水準集合と群の因子で識別子が重なっている: ' + '、'.join(both))
    if lserr:
        sys.exit('ERROR: 水準集合の宣言と ARD が合わない' + ''.join(
            chr(10) + '  ' + e for e in lserr))

    # 集団・部分集団も同じ扱いにする。set_obj は条件の行が無ければ id と name だけの殻を
    # 返すので、ARD が宣言の無い識別子を使っても黙って通っていた。Out-5.4.7.3 の SS-DA が
    # この状態で、仕様書に定義の無い識別子が ReportingEvent の DataSubset として出ていた
    # （2026-09-05。issues.md）。条件を書けないものは note だけの行を置くという先例が
    # SS-RFSPN にあるので、行そのものが無い状態を許す理由が無い
    cnd = cond or {}
    nodecl = sorted(s for s in (sets | subsets) if s not in cnd)
    if nodecl:
        sys.exit('analysis-set-condition.csv に宣言の無い集団・部分集団を ARD が'
                 '使っている: ' + '、'.join(nodecl)
                 + '。docs/validation/acceptance/analysis-set-condition.csv へ行を'
                   '足すこと（条件が単一の式で表せないものは note に理由を書く）')

    # --- AnalysisMethod と、その子の Operation ---
    # ops は「その手法を使ういずれかの解析が出した操作」の集合である。ある解析が
    # 実施していない操作まで手法に並ぶと、手法の定義が実態より広くなる。ARD が
    # (method_id, operation_id) の組で持つ以上、手法をまたぐ混入は起きないが、
    # 同じ手法の中で解析ごとに操作が違う場合はここに現れる。件数を実行時に報告して
    # 気づけるようにする（C2-154）
    by_method = collections.defaultdict(list)
    for mid, oid, lbl in sorted(ops):
        by_method[mid].append({'id': oid, 'name': oid.split('.', 1)[-1], 'label': lbl,
                               'order': len(by_method[mid]) + 1})
    method_objs = []
    for m in sorted(methods):
        o = {'id': m, 'name': m, 'operations': by_method[m]}
        c = (mcode or {}).get(m)
        if c:
            o['codeTemplate'] = {'context': c['context'], 'code': c['code']}
            if c.get('document_id'):
                o['codeTemplate']['documentRef'] = {'referenceDocumentId': c['document_id']}
            o['documentRefs'] = [{'referenceDocumentId': 'DOC-ARS'}]
        method_objs.append(o)

    # VARIABLE-LEVEL の因子を立てるのは、水準集合の宣言が無い水準が1つでも残るときだけ。
    # 全部が事前規定の集合へ移れば、この因子は出ない
    any_varlevel = any(r.get('variable_level') and not r.get('level_set')
                       for d in per_analysis.values() for r in d['rows'])

    # --- Analysis ---
    analyses = []
    n_empty = [0]   # rawValue を持たない ARD 行の数（C2-150）
    for aid, d in per_analysis.items():
        meta = d['meta']
        oid = meta.get('output_id') or ''
        pu_out, pu_an = purposes
        pu = pu_an.get(aid) or pu_out.get(oid)
        # 既定値で埋めない。値が無いまま通すと、根拠を確かめていない解析が
        # EXPLORATORY OUTCOME MEASURE と SPECIFIED IN SAP を名乗って出ていく（C2-149）
        if pu is None or not pu.get('purpose') or not pu.get('reason'):
            sys.exit(f'purpose か reason が無い: 解析 {aid}（Output {oid or "不明"}）。'
                     f'docs/metadata/analysis-purpose.csv へ行を足すこと')
        # name は人が読む名前で、id とは役割が違う。集団・サブセット・変数・群から
        # 組み立てる（C2-143）。材料が無いときだけ id へ落とす
        nm = ' / '.join(x for x in (
            meta.get('analysis_set'), meta.get('data_subset'),
            meta.get('variable'), meta.get('group1')) if x)
        a = {
            'id': aid,
            'name': f'{aid}: {nm}' if nm else aid,
            'reason': {'controlledTerm': pu['reason']},
            'purpose': {'controlledTerm': pu['purpose']},
            'methodId': meta.get('method_id') or '',
        }
        # reason は「いつ計画されたか」を述べるだけなので、それだけでは受領者は主張を
        # 裏づけられない。CSV の note（規定の節・事後追加の経緯）を description に写し、
        # reason に対応する文書を documentRefs で指す（C3-006）。対応は
        # reference-documents.csv の for_reason 列が持ち、DATA DRIVEN のように事前に
        # 規定した文書が無いものは空になる
        if pu.get('note'):
            a['description'] = pu['note']
        dids = (dref or {}).get(pu['reason'], [])
        if dids:
            a['documentRefs'] = [{'referenceDocumentId': i} for i in dids]
        if meta.get('analysis_set'):
            a['analysisSetId'] = meta['analysis_set']
        if meta.get('data_subset'):
            a['dataSubsetId'] = meta['data_subset']
        # ARS の Analysis.dataset は解析に使ったデータセットの名前で、絞り込みは
        # analysisSetId と dataSubsetId が持つ。SAS 系の ARD は由来を
        # 「ads.adtte(where=(FASFL='Y' and PARAMCD='<パラメータ>'))」という SAS の構文で持つので、
        # データセット名だけを取り出して標準の意味に合わせる。R 系は ADaM の名前を
        # そのまま持つ。名前が取れないときは出さない（C2-162・C2-156）。
        # 主たる出所は両系統とも呼び出し側が名指ししており、ここで表を引いて写すことは
        # しない（C2-211。写しは編集のたびにズレる）
        ds = re.sub(r'^\w+\.', '', (meta.get('src_data') or '').split('(')[0]).strip().upper()
        if ds:
            a['dataset'] = ds
        if meta.get('variable'):
            a['variable'] = meta['variable']
        # orderedGroupings は、その解析が結果を分けている軸の並びである。下の resultGroups
        # が指す因子はここに現れなければ、受領者はその軸の定義へ辿れない。2026-08-31 まで
        # group1 だけを並べていたため、resultGroups の 28,771 件（全 52,421 件のうち）が
        # orderedGroupings に無い VARIABLE-LEVEL を指していた（C3-008）。軸は結果行の側から
        # 集める。order は並べた順に振り、group1 と重ならないようにする
        ogs = []
        # resultsByGroup は OrderedGroupingFactor の必須スロット。結果値を群ごとに
        # 分けて報告するかどうかを表す。本試験の ARD は群ごとに行を分けており、
        # その群は下の resultGroups に現れるので真になる
        if meta.get('group1'):
            ogs.append({'order': len(ogs) + 1, 'groupingId': meta['group1'],
                        'resultsByGroup': True})
        # 変数の水準も結果を分ける軸で、下の resultGroups がその因子として指す。事前規定の
        # 水準集合を渡した集計はその集合の因子、渡していない集計は VARIABLE-LEVEL になる。
        # 1つの解析が両方を持つこともあるので、行の側から軸を集める（C3-002・C3-008）
        axes = []
        for r in d['rows']:
            if not r.get('variable_level'):
                continue
            ax = r.get('level_set') or 'VARIABLE-LEVEL'
            if ax not in axes:
                axes.append(ax)
        for ax in axes:
            ogs.append({'order': len(ogs) + 1, 'groupingId': ax,
                        'resultsByGroup': True})
        if ogs:
            a['orderedGroupings'] = ogs
        if meta.get('output_id'):
            a['categoryIds'] = [meta['output_id']]

        results = []
        for r in d['rows']:
            # rawValue は丸めを適用しない値。数値と文字のどちらかが入る
            raw = r.get('stat_num') if r.get('stat_type') == 'num' else r.get('stat_char')
            res = {'operationId': r.get('operation_id') or ''}
            groups = []
            if r.get('group1') and r.get('group1_level'):
                # 事前規定の群は groupId で Group を指し、データ由来の群は groupValue で
                # 実際の値を持つ。どちらかは analysis-grouping.csv が決める（C2-140・C2-142）
                gd = grp[r['group1']]['data_driven']
                k = 'groupValue' if gd else 'groupId'
                groups.append({'groupingId': r['group1'], k: r['group1_level']})
            if r.get('variable_level'):
                # 変数の水準も結果を分ける軸なので resultGroups で表す。2026-08-30 まで
                # 変数名そのものを groupingId にしていたため、150種類の因子が
                # analysisGroupings に無いまま参照されていた（C2-141・C2-142）。
                # 事前規定の水準集合から出た水準はその集合の因子を groupId で指し、
                # 集合の宣言が無い水準は VARIABLE-LEVEL のデータ由来として groupValue で
                # 持つ（C3-002。2026-09-05）
                if r.get('level_set'):
                    groups.append({'groupingId': r['level_set'],
                                   'groupId': r['variable_level']})
                else:
                    groups.append({'groupingId': 'VARIABLE-LEVEL',
                                   'groupValue': r['variable_level']})
            if groups:
                res['resultGroups'] = groups
            if raw not in (None, ''):
                res['rawValue'] = str(raw)
            else:
                # 値が無いのは、生存時間の中央値に到達していない群や n=1 の標準偏差など、
                # 推定できないことがそれ自体の結果である場合である。値の無い結果オブジェクトを
                # そのまま置くと「結果はあるが値は無い」という区別の付かない状態になるので、
                # 推定不能であることを formattedValue で明示する（C2-150）
                res['formattedValue'] = 'NE'
                n_empty[0] += 1
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
        # fileSpecifications は、その図表が実際にどのファイルとして配布されるかを
        # 指す。これが無いと ReportingEvent から成果物へ辿れず、第三者は結果値と
        # 図表の対応を確かめられない（C2-163）。納品パッケージ内の相対パスで持つ
        outputs.append({
            'id': lbl, 'name': nm,
            'displays': [{'order': 1, 'display': {'id': lbl + '-D1', 'name': nm,
                                                  'displayTitle': nm}}],
            # fileType は ARS の列挙が pdf・rtf・txt しか持たない。HTML を名乗るには
            # TerminologyExtension でスポンサー定義の語を足す必要があるので、ここでは
            # 型を宣言せず label に書く。必須スロットは name だけである
            'fileSpecifications': [
                {'name': f'{lbl}.html', 'label': 'HTML（日本語）',
                 'location': f'14_tlf/ja/{lbl}.html'},
                {'name': f'{lbl}.html', 'label': 'HTML（英語）',
                 'location': f'14_tlf/en/{lbl}.html'},
            ],
        })
        aid = (row.get('analysis_id') or '').strip()
        if aid:
            lbl_to_analyses[lbl].append(aid)

    # mainListOfContents.contentsList は NestedList（listItems を持つ入れ子）であって
    # 項目の配列ではない。各項目は OrderedListItem で level・order・name が必須。
    # 本試験は入れ子にせず、図表を宣言の順（章番号順）に1階層で並べる
    # 図表の下に、その図表を構成する解析を第2階層で並べる。ARS が Output から Analysis を
    # 直接指すスロットを持たないため、両者の関係はここか AnalysisOutputCategorization に
    # しか残らない。宣言（tlf-index.csv）が持つ対応を写さないと、ReportingEvent だけを
    # 渡された相手はどの解析がどの図表になったのかを辿れない（C2-147）
    for i, o in enumerate(outputs, 1):
        item = {'level': 1, 'order': i, 'name': o['name'], 'outputId': o['id']}
        ans = lbl_to_analyses.get(o['id'], [])
        if ans:
            item['sublist'] = {'listItems': [
                {'level': 2, 'order': j, 'name': aid, 'analysisId': aid}
                for j, aid in enumerate(ans, 1)]}
        contents.append(item)

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
        # 結果値の出どころを辿るための文書。納品パッケージ内の位置を持つ（C2-162）
        'referenceDocuments': refdocs or [],
        # AnalysisSet と DataSubset は level と order が必須（入れ子にできる定義のため）。
        # 本試験はどちらも入れ子を持たないので level は 1 で、order は識別子の順に振る
        'analysisSets': [set_obj(s, i, cond or {})
                         for i, s in enumerate(sorted(sets), 1)],
        'dataSubsets': [set_obj(s, i, cond or {})
                        for i, s in enumerate(sorted(subsets), 1)],
        # dataDriven は GroupingFactor の必須スロットで、群が事前に規定されたものか、
        # 変数の相異なるデータ値から得られたものかを表す。値は analysis-grouping.csv の
        # data_driven 列が持ち、ここで既定へ落とすことはしない（C2-142・C3-001）
        # 変数の水準を表す因子。ARD の variable_level 列が値を持つ行に付く（C2-141）。
        # dataDriven=True は「群が groupingVariable の相異なるデータ値から得られた」ことを
        # 表すので、その変数を指さないまま真を名乗ると真の指す先が無い。2026-08-31 まで
        # id・name・label・dataDriven の4つだけを持っていた（C3-002）。水準の出どころは
        # ARD の variable_level 列なので、台となるデータセットと変数をここで名指しする。
        # groupingDataset は他の因子が ADaM の名前を大文字で置くのに合わせて ARD と書く
        # （上の Analysis.dataset が ard.ard を ARD へ写すのと同じ書式）。変数名は
        # ard_cards.csv の列名そのままで、ADaM 変数のような大文字ではない
        'analysisGroupings': [grouping_obj(g, grp, lvlabels or {})
                              for g in sorted(groupings)]
                             + [levelset_obj(s, lsets[s], lvlabels or {})
                                for s in sorted(used_ls)]
                             + ([{'id': 'VARIABLE-LEVEL', 'name': 'VARIABLE-LEVEL',
                                  'label': '解析変数の水準', 'dataDriven': True,
                                  'groupingDataset': 'ARD',
                                  'groupingVariable': 'variable_level'}]
                                if any_varlevel else []),
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
    pmap = purpose_map()
    refdocs, dref = read_reference_docs()
    re_obj = build(cards, label_map(), pmap, tlf_index(), read_conditions(),
                   refdocs, read_method_code(a.system),
                   read_groupings(), dref, read_level_sets(), level_label_map())

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(re_obj, f, ensure_ascii=False, indent=2)

    n_res = sum(len(x['results']) for x in re_obj['analyses'])
    print(f'{src} を読んだ（{len(cards):,} 行）')
    print(f'{out} を書いた')
    print(f'  解析 {len(re_obj["analyses"]):,} / 結果値 {n_res:,} / 図表 {len(re_obj["outputs"])}')
    # Output 単位の既定を解析単位で上書きした件数。綴りを間違えると黙って効かなくなり、
    # 既定が行き渡ったまま通ってしまうので、効かなかった行はその場で落とす（C2-145）
    ids = {x['id'] for x in re_obj['analyses']}
    miss = sorted(k for k in pmap[1] if k not in ids)
    if miss:
        sys.exit('analysis-purpose.csv の analysis_id が解析に無い: ' + '、'.join(miss))
    if pmap[1]:
        print(f'  purpose・reason を解析単位で上書きした解析 {len(pmap[1])} 件（C2-145）')
    n_ne = sum(1 for x in re_obj['analyses'] for r in x['results']
               if r.get('formattedValue') == 'NE')
    if n_ne:
        print(f'  推定不能として NE を入れた結果値 {n_ne:,}（C2-150）')
    # 同じ手法を使う解析のあいだで、実施した操作の集合が違うものを数える（C2-154）
    by_m = collections.defaultdict(set)
    for x in re_obj['analyses']:
        by_m[x.get('methodId', '')].add(
            tuple(sorted({r.get('operationId', '') for r in x['results']})))
    uneven = {m: len(v) for m, v in by_m.items() if len(v) > 1}
    if uneven:
        print('  手法の中で解析ごとに操作の集合が違う: '
              + '、'.join(f'{m} {n} 通り' for m, n in sorted(uneven.items())))
    n_ls = sum(1 for g in re_obj['analysisGroupings'] if g['id'].startswith('LS_'))
    n_vl = sum(1 for g in re_obj['analysisGroupings'] if g['id'] == 'VARIABLE-LEVEL')
    print(f'  集団 {len(re_obj["analysisSets"])} / サブセット {len(re_obj["dataSubsets"])} '
          f'/ 群 {len(re_obj["analysisGroupings"])} / 手法 {len(re_obj["methods"])}')
    print(f'  うち事前規定の水準集合 {n_ls} 件'
          + ('、データ由来の水準（VARIABLE-LEVEL）が残る' if n_vl else
             '、VARIABLE-LEVEL は残っていない'))


if __name__ == '__main__':
    main()
