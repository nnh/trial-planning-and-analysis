# check-ars-json.py
#
# ReportingEvent の JSON を CDISC ARS v1.0 のスキーマで検証する。
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
        return 0
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
    return rc


if __name__ == '__main__':
    sys.exit(main())
