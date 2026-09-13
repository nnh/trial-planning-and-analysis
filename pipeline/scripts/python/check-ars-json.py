# check-ars-json.py
#
# ReportingEvent の JSON を CDISC ARS v1.0 のスキーマで検証する。
#
# この検査が言えるのは「ARS v1.0 の JSON-Schema に適合する」ことと「ID 参照が整合する」
# ことだけである。解析の妥当性は言えない。適合したまま誤りうるものを挙げると、解析の
# 名称、集団やサブセットの選択条件が実際の集団と合っているか、手法が本当にその解析の
# 導出を表しているか、Output と結果値の対応、そして結果値そのものの正しさである。
# 合否を報告するときは「標準への適合」と「解析の妥当性」を別の項目として書く（C2-151）。
#
# 適合したまま誤りうるものを、どの検査が見ているか（C2-004・C2-023）。
#   行数と行の水準の並び      docs/validation/acceptance/display-contract.csv と CompareTLF.R の受入基準
#   分母（集団・部分集団）    同 display-contract.csv と check-ars-tlf.py の受入基準
#   結果値そのもの            compare-ars-json.py（両系統の全結果値を相対許容差 1e-8 で比較）
#   Output と結果値の対応      check-ars-tlf.py（宣言・セル台帳・ARD・ReportingEvent の照合）
#   主要評価項目の判定        check-ars-tlf.py（閾値と比較の向きから出し直す。C2-155）
#   宣言済みの図表の欠落      CompareTLF.R（tlf-index.csv を正本とする照合。C2-015）
# どれも「メタデータが正しければ実データも正しい」という前提を置かない。メタデータと
# 実データを別々に読んで突き合わせる形にしてある。
#
# スキーマの正本は標準の LinkML モデルで、そこから生成された JSON-Schema を
# docs/metadata/external/ars-v1-0.schema.json へ写してある（出どころと取得日は
# 同ディレクトリの README）。網に出て取り直さないのは、検証の結果が実行のたびに
# 変わらないようにするため。標準が改訂されたら写しを更新して差分を見る。
#
# なぜ自前の検査で済ませないか。2026-08-29 まで、必須スロットを数個だけ見る検査を
# compare-ars-json.py に書いて「準拠」と判断していた。スキーマにかけたところ1,319件の
# 違反が出た（OrderedGroupingFactor の resultsByGroup、Output の displays、
# AnalysisSet と DataSubset の level・order、GroupingFactor の dataDriven、
# mainListOfContents の入れ子の形）。自前の検査は書いた分しか見ない。
#
# 依存。jsonschema が要る。リポジトリの他の Python は標準ライブラリだけで動かす方針
# （nnh/trial-planning-and-analysis の analysis-pipeline-plan.md）なので、この1本だけを
# 例外にし、入っていなければ検証を「できなかった」として終了コード2で返す。合否
# （0 と 1）と区別できるようにするため、黙って通さない。
#
#   python -m pip install jsonschema
#
# 使い方
#   python scripts/check-ars-json.py                 ... 両系統の JSON を検証する
#   python scripts/check-ars-json.py --system r      ... 片方だけ
#   python scripts/check-ars-json.py --json <path>   ... ファイルを直接指定
#
# 終了コード
#   0 違反なし / 1 違反あり / 2 検証できなかった（jsonschema かスキーマか JSON が無い）
import sys, os, json, argparse, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(REPO, 'docs', 'metadata', 'external', 'ars-v1-0.schema.json')


def targets(system):
    """検証する JSON。系統ごとに置き場が違う（datasets/<系統>/ard/）"""
    box = boxpath.trial_dir()
    out = []
    for s in (('sas', 'r') if system == 'both' else (system,)):
        p = os.path.join(box, 'datasets', s, 'ard', f'reporting-event-{s}.json')
        out.append((s, p))
    return out


def refs(doc):
    """ID 参照の行き先が実在するかと、群の指し方が定義と合っているかを見る（C2-148）。

    JSON-Schema は型・列挙値・必須スロットしか見ない。存在しない `methodId` を指しても、
    事前規定の群を `groupValue` で指しても、形は正しいので通る。参照が切れた
    ReportingEvent は、受け取った側が解析の定義を辿れないという点でスキーマ違反と
    同じ重さを持つ。

    結果値の `operationId` は、所属する解析の `methodId` が指す手法の Operation でなければ
    ならない。ID の実在だけを見て手法との対応を見ないと、統計値が別の手法の操作へ
    結び付いていても通る（C3-011）。`documentRefs` は Analysis だけでなく手法・図表と
    コードの参照にもあるので、置き場を問わずまとめて見る（C3-012）。

    結果の `resultGroups` が指す因子が、その解析の `orderedGroupings` に現れているかも
    見る。因子の実在だけを見ていると、解析の側からは宣言されていない軸で結果が分かれた
    ままになる（C3-008）。これは当面は診断として件数だけを報告し、終了コードには
    加えない。
    """
    ids = {k: {x['id'] for x in doc.get(k, []) if 'id' in x}
           for k in ('analyses', 'outputs', 'methods', 'analysisSets', 'dataSubsets',
                     'analysisGroupings', 'referenceDocuments',
                     'analysisOutputCategorizations')}
    # 群の定義。事前規定（dataDriven=false）は groupId で Group を指し、データ由来は
    # groupValue で実際の値を持つ
    gdef = {g['id']: g for g in doc.get('analysisGroupings', []) if 'id' in g}
    # 手法ごとの Operation。結果値の operationId の行き先はこの集合に限られる
    mops = {m['id']: {o.get('id') for o in m.get('operations', []) or []}
            for m in doc.get('methods', []) if 'id' in m}
    cats = set()
    for c in doc.get('analysisOutputCategorizations', []):
        for x in c.get('categories', []):
            if 'id' in x:
                cats.add(x['id'])
    bad = collections.Counter()
    # 停止条件にしない診断。件数だけを報告する（C3-008）。run-release.py が回す検査の
    # 途中で止まると後続の段階が確認できず、また ARD を作り直すまでは古い生成物が
    # 残っている端末があるため、当面は合否に加えない
    diag = collections.Counter()

    def chk(kind, val, pool):
        if val and val not in pool:
            bad[f'{kind} の参照先が無い'] += 1

    def chk_docs(kind, obj):
        """文書への参照をまとめて見る。documentRefs のほか、手法の codeTemplate と
        図表・解析の programmingCode も文書を1つ指す。置き場ごとに書き足していた頃は
        Analysis の documentRefs しか見ておらず、解析コードへの参照が切れても通った
        （C3-012）"""
        for d in obj.get('documentRefs') or []:
            chk(f'{kind}.documentRefs', d.get('referenceDocumentId'),
                ids['referenceDocuments'])
        for slot in ('codeTemplate', 'programmingCode'):
            d = (obj.get(slot) or {}).get('documentRef')
            if d:
                chk(f'{kind}.{slot}.documentRef', d.get('referenceDocumentId'),
                    ids['referenceDocuments'])

    for m in doc.get('methods', []):
        chk_docs('methods', m)
    for o in doc.get('outputs', []):
        chk_docs('outputs', o)

    for a in doc.get('analyses', []):
        chk('methodId', a.get('methodId'), ids['methods'])
        chk('analysisSetId', a.get('analysisSetId'), ids['analysisSets'])
        chk('dataSubsetId', a.get('dataSubsetId'), ids['dataSubsets'])
        for cid in a.get('categoryIds', []) or []:
            chk('categoryIds', cid, cats)
        chk_docs('analyses', a)
        ogids = set()
        for og in a.get('orderedGroupings', []) or []:
            chk('orderedGroupings.groupingId', og.get('groupingId'),
                ids['analysisGroupings'])
            ogids.add(og.get('groupingId'))
        ops = mops.get(a.get('methodId'))
        for r in a.get('results', []):
            # 接頭辞が一致するかではなく、その解析の手法が持つ Operation の ID かを見る。
            # 手法の参照が切れているときは methodId の側で数えているので重ねて数えない
            if ops is not None and r.get('operationId') not in ops:
                bad['operationId が解析の手法の Operation に無い'] += 1
            for g in r.get('resultGroups', []) or []:
                gid = g.get('groupingId')
                chk('resultGroups.groupingId', gid, ids['analysisGroupings'])
                # 因子が ReportingEvent に実在するだけでは足りない。結果を分けている軸は
                # その解析の orderedGroupings に現れていなければ、受領者は結果がどの軸で
                # 分かれているかを解析の側から辿れない（C3-008）
                if gid not in ogids:
                    diag['resultGroups.groupingId が解析の orderedGroupings に無い'
                         f'（{gid}）'] += 1
                d = gdef.get(gid)
                if d is None:
                    continue
                dd = bool(d.get('dataDriven'))
                if dd and g.get('groupId'):
                    bad['データ由来の群を groupId で指している'] += 1
                if not dd and g.get('groupValue') and not g.get('groupId'):
                    bad['事前規定の群を groupValue で指している'] += 1
                if (not dd and g.get('groupId')
                        and g['groupId'] not in {x.get('id') for x in d.get('groups', [])}):
                    bad['事前規定の群に無い groupId を指している'] += 1

    def walk(items):
        for it in items or []:
            chk('mainListOfContents.outputId', it.get('outputId'), ids['outputs'])
            chk('mainListOfContents.analysisId', it.get('analysisId'), ids['analyses'])
            walk((it.get('sublist') or {}).get('listItems'))
    walk(((doc.get('mainListOfContents') or {}).get('contentsList') or {}).get('listItems'))

    if diag:
        print(f'  診断（合否に加えない）{sum(diag.values())} 件（{len(diag)} 種）')
        for k, n in sorted(diag.items(), key=lambda x: -x[1]):
            print(f'    {n:6d}  {k}')
    if not bad:
        print('  参照の不整合 0 件')
        return 0
    print(f'  参照の不整合 {sum(bad.values())} 件（{len(bad)} 種）')
    for k, n in sorted(bad.items(), key=lambda x: -x[1]):
        print(f'    {n:6d}  {k}')
    return 1


def report(tag, path, validator):
    doc = json.load(open(path, encoding='utf-8'))
    errs = list(validator.iter_errors(doc))
    n_an = len(doc.get('analyses', []))
    n_ou = len(doc.get('outputs', []))
    n_re = sum(len(a.get('results', [])) for a in doc.get('analyses', []))
    print(f'{tag}: {os.path.basename(path)}')
    print(f'  解析 {n_an} 件 / 結果値 {n_re} 件 / 図表 {n_ou} 件')
    if not errs:
        print('  スキーマ違反 0 件')
        return refs(doc)
    # 同じ型の違反が数千件出るので、置き場とメッセージでまとめて数える
    grp = collections.Counter()
    where = {}
    for e in errs:
        p = list(e.absolute_path)
        key = (p[0] if p else '(root)', e.validator, e.message[:70])
        grp[key] += 1
        where.setdefault(key, []).append('/'.join(str(x) for x in p))
    print(f'  スキーマ違反 {len(errs)} 件（{len(grp)} 種）')
    for (top, kind, msg), n in sorted(grp.items(), key=lambda x: -x[1]):
        print(f'    {n:6d}  {top} [{kind}] {msg}')
        print(f'            例: {where[(top, kind, msg)][:2]}')
    refs(doc)
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--system', choices=['sas', 'r', 'both'], default='both')
    ap.add_argument('--json', help='検証するファイルを直接指定する')
    ap.add_argument('--schema', default=SCHEMA)
    a = ap.parse_args()

    try:
        from jsonschema import Draft7Validator
    except ImportError:
        print('ERROR: jsonschema が無いので検証できない。'
              'python -m pip install jsonschema')
        return 2
    if not os.path.exists(a.schema):
        print(f'ERROR: スキーマが無い: {a.schema}')
        return 2

    schema = json.load(open(a.schema, encoding='utf-8'))
    Draft7Validator.check_schema(schema)
    print(f'スキーマ: {schema.get("$id")}（{os.path.basename(a.schema)}）')
    validator = Draft7Validator(schema)

    items = [('指定', a.json)] if a.json else targets(a.system)
    rc = 0
    for tag, p in items:
        if not os.path.exists(p):
            print(f'ERROR: JSON が無い: {p}')
            return 2
        rc = max(rc, report(tag, p, validator))
    print('違反 0 件' if rc == 0 else '違反あり')
    if rc == 0:
        print('  ここで言えるのは ARS v1.0 のスキーマへの適合と ID 参照の整合だけで、'
              '解析の妥当性は別に確かめること（集団の条件・手法・結果値の正しさ）')
    return rc


if __name__ == '__main__':
    sys.exit(main())
