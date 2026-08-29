# compare-ars-json.py
#
# SAS系と R系の ReportingEvent（ARS v1.0 の JSON）を突き合わせる。
#
# 既存の Compare.R は ard_cards.csv 同士を比べていた。ARS 準拠へ移った後は
# ReportingEvent が正本になるので、突合もそちらで行う（ars-migration-plan.md 第5段）。
#
# 突合の単位は OperationResult。キーは Analysis.id・operationId・resultGroups の3つ。
# resultGroups は順序に依らないよう並べ替えてから比べる。
#
# 判定
#   - 構造（analyses・outputs・methods・analysisSets 等の集合）が一致するか
#   - 各 OperationResult の rawValue が一致するか。数値は相対許容差、文字は完全一致
#   - 片側にしかない結果値が無いか
#
# 許容差は ard-double-coding-spec.md「許容差」に合わせて相対 1e-8。
#
# 使い方
#   python scripts/compare-ars-json.py
#   python scripts/compare-ars-json.py --a <path> --b <path>
import sys, os, json, argparse, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath
sys.stdout.reconfigure(encoding='utf-8')

TOL = 1e-8


def load(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def result_key(analysis_id, res):
    g = tuple(sorted((x.get('groupingId', ''), x.get('groupId', ''))
                     for x in res.get('resultGroups', [])))
    return (analysis_id, res.get('operationId', ''), g)


def flatten(re_obj):
    out = {}
    for a in re_obj.get('analyses', []):
        for r in a.get('results', []):
            out[result_key(a['id'], r)] = r.get('rawValue', '')
    return out


def as_num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def cmp_sets(name, a, b, err):
    """id の集合を比べる。片側にしかないものを報告する"""
    sa = {x['id'] for x in a}
    sb = {x['id'] for x in b}
    if sa != sb:
        only_a, only_b = sorted(sa - sb), sorted(sb - sa)
        err.append(f'{name}: A のみ {len(only_a)} 件 {only_a[:5]} / '
                   f'B のみ {len(only_b)} 件 {only_b[:5]}')
    return len(sa | sb)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--a')
    ap.add_argument('--b')
    args = ap.parse_args()

    box = boxpath.trial_dir()
    pa = args.a or os.path.join(box, 'datasets', 'sas', 'ard', 'reporting-event-sas.json')
    pb = args.b or os.path.join(box, 'datasets', 'r', 'ard', 'reporting-event-r.json')
    for p in (pa, pb):
        if not os.path.isfile(p):
            sys.exit(f'ReportingEvent が無い: {p}')

    A, B = load(pa), load(pb)
    print(f'A: {os.path.basename(pa)}')
    print(f'B: {os.path.basename(pb)}')

    err = []
    n_an = cmp_sets('analyses', A.get('analyses', []), B.get('analyses', []), err)
    n_ou = cmp_sets('outputs', A.get('outputs', []), B.get('outputs', []), err)
    cmp_sets('methods', A.get('methods', []), B.get('methods', []), err)
    cmp_sets('analysisSets', A.get('analysisSets', []), B.get('analysisSets', []), err)
    cmp_sets('dataSubsets', A.get('dataSubsets', []), B.get('dataSubsets', []), err)
    cmp_sets('analysisGroupings', A.get('analysisGroupings', []),
             B.get('analysisGroupings', []), err)

    # 必須スロットが埋まっているか（ARS v1.0）
    for label, obj in (('A', A), ('B', B)):
        for a in obj.get('analyses', []):
            for slot in ('id', 'name', 'methodId'):
                if not a.get(slot):
                    err.append(f'{label}: Analysis {a.get("id")} の必須 {slot} が空')
                    break
            if not a.get('reason', {}).get('controlledTerm'):
                err.append(f'{label}: Analysis {a.get("id")} の reason が空')
            if not a.get('purpose', {}).get('controlledTerm'):
                err.append(f'{label}: Analysis {a.get("id")} の purpose が空')

    fa, fb = flatten(A), flatten(B)
    only_a = set(fa) - set(fb)
    only_b = set(fb) - set(fa)

    n_num = n_chr = 0
    bad = []
    for k in set(fa) & set(fb):
        va, vb = fa[k], fb[k]
        na, nb = as_num(va), as_num(vb)
        if na is not None and nb is not None:
            n_num += 1
            d = abs(na - nb)
            rel = d / max(abs(na), abs(nb)) if max(abs(na), abs(nb)) > 0 else d
            if rel > TOL:
                bad.append((k, va, vb, rel))
        else:
            n_chr += 1
            if str(va) != str(vb):
                bad.append((k, va, vb, None))

    print(f'解析 {n_an:,} / 図表 {n_ou}')
    print(f'結果値 A {len(fa):,} / B {len(fb):,}')
    print(f'  数値 {n_num:,} 件 / 文字 {n_chr:,} 件')
    print(f'  片側にのみある結果値 : A {len(only_a)} / B {len(only_b)}')
    for k in sorted(only_a)[:3]:
        print(f'    A のみ: {k}')
    for k in sorted(only_b)[:3]:
        print(f'    B のみ: {k}')
    print(f'  値の不一致 : {len(bad)} 件')
    for k, va, vb, rel in bad[:5]:
        r = f'相対差 {rel:.3e}' if rel is not None else '文字が違う'
        print(f'    {k} : A={va} B={vb} {r}')

    for e in err[:10]:
        print('ERROR:', e)
    if len(err) > 10:
        print(f'ERROR: ほか {len(err) - 10} 件')

    ok = not err and not only_a and not only_b and not bad
    print('結果 : ' + ('構造と全結果値が一致した。' if ok else '一致しない。上を確認すること。'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
