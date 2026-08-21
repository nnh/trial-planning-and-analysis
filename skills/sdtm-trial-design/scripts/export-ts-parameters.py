"""Trial Design ドメインを作るための材料を CDISC の定義から引く。

TS の `TSPARMCD` は数が多く（CT に129種）、そのうち何が必須かは SDTMIG の
Appendix C1 と CDISC の適合性ルールが決めている。手で調べると時間がかかり、
版が変わると内容も変わるので、CDISC CORE のキャッシュ（元は CDISC Library）から
引く。

出せるもの。

  --required   必須の TSPARMCD と、その TSPARM（CT の対応する用語）
  --values     値に CT が使われるパラメータの選択肢（TPHASE・TBLIND など）
  --domains    Trial Design 5ドメインの変数と Core（Required/Expected/Permissible）
  --skeleton   ts.csv の骨組み（必須パラメータの行。tsval は空）
  （省略時は --required --values --domains をまとめて出す）

    python export-ts-parameters.py [--required] [--values] [--domains] [--skeleton]
                                   [--ct sdtmct-2026-03-27] [--ig 3-2] [--cache <dir>]

必須の一覧は CORE のルール CORE-000740（CDISC CG0287）の条件から読む。FDA が求める
組（CORE-000741 の INTMODEL・INTTYPE・PCLASS）も併せて出す。ルール定義が変わったら
出力も変わるので、作業のたびに実行して確かめる。
"""
import argparse
import ast
import csv
import io
import os
import pickle
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

DEFAULT_CACHE = os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')),
                             'opt', 'cdisc-core', 'core', 'resources', 'cache')
TD_DOMAINS = ('TS', 'TA', 'TE', 'TI', 'TV', 'TD')
# 値に CT を使うパラメータ。TSPARMCD → その値の codelist
VALUE_CODELISTS = {
    'STYPE': 'STYPE', 'TPHASE': 'TPHASE', 'TBLIND': 'TBLIND', 'TCNTRL': 'TCNTRL',
    'INTMODEL': 'INTMODEL', 'TINDTP': 'TINDTP', 'SEXPOP': 'SEXPOP',
    'TTYPE': 'TTYPE', 'INTTYPE': 'INTTYPE',
    'RANDOM': 'NY', 'ADDON': 'NY', 'ADAPT': 'NY', 'HLTSUBJI': 'NY',
}


def load(cache, name):
    p = os.path.join(cache, name)
    if not os.path.exists(p):
        raise SystemExit(f'CORE のキャッシュがありません: {p}\n'
                         f'--cache でディレクトリを指定してください。')
    with open(p, 'rb') as f:
        return pickle.load(f)


def pick_ct(cache, want):
    """CT のファイル名。省略時はいちばん新しい sdtmct を選ぶ。"""
    if want:
        return want if want.endswith('.pkl') else want + '.pkl'
    cands = sorted(f for f in os.listdir(cache) if f.startswith('sdtmct-'))
    if not cands:
        raise SystemExit(f'sdtmct のキャッシュが {cache} にありません')
    return cands[-1]


def ct_terms(codelists, sv):
    for c in codelists:
        if c.get('submissionValue') == sv:
            t = c.get('terms')
            if isinstance(t, str):
                t = ast.literal_eval(t)
            return c, t
    return None, None


def required_from_rules(rules):
    """CORE-000740 の条件から必須 TSPARMCD、CORE-000741 から FDA の組を読む。"""
    req, fda = [], []
    r = rules.get('CORE-000740')
    if r:
        def walk(node):
            if isinstance(node, dict):
                v = node.get('value')
                if isinstance(v, dict) and v.get('target') == 'TSPARMCD':
                    c = v.get('comparator')
                    if isinstance(c, list):
                        req.extend(c)
                for x in node.values():
                    walk(x)
            elif isinstance(node, list):
                for x in node:
                    walk(x)
        walk(r.get('conditions'))
    r = rules.get('CORE-000741')
    if r:
        s = str(r.get('conditions'))
        for k in ('INTMODEL', 'INTTYPE', 'PCLASS'):
            if k in s:
                fda.append(k)
    # 重複を除いて順序を保つ
    seen = set()
    req = [x for x in req if not (x in seen or seen.add(x))]
    return req, fda


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cache', default=DEFAULT_CACHE)
    ap.add_argument('--ct', help='CT のキャッシュ名（省略時は最新の sdtmct）')
    ap.add_argument('--ig', default='3-2', help='SDTM IG の版（既定 3-2）')
    ap.add_argument('--required', action='store_true')
    ap.add_argument('--values', action='store_true')
    ap.add_argument('--domains', action='store_true')
    ap.add_argument('--skeleton', action='store_true', help='ts.csv の骨組みを標準出力へ')
    a = ap.parse_args()
    if not any((a.required, a.values, a.domains, a.skeleton)):
        a.required = a.values = a.domains = True

    ctname = pick_ct(a.cache, a.ct)
    ct = load(a.cache, ctname)
    codelists = ct['codelists']
    rules = load(a.cache, 'rules.pkl')
    print(f'CT: {ctname} / IG: {a.ig} / キャッシュ: {a.cache}')

    # TSPARMCD → TSPARM（conceptId で結ぶ）
    _, cd = ct_terms(codelists, 'TSPARMCD')
    _, nm = ct_terms(codelists, 'TSPARM')
    if cd is None or nm is None:
        raise SystemExit('CT に TSPARMCD / TSPARM がありません')
    cd_by_cid = {x['conceptId']: x for x in cd}
    nm_by_cid = {x['conceptId']: x for x in nm}
    parm_of = {v['submissionValue']: nm_by_cid.get(k, {}).get('submissionValue', '')
               for k, v in cd_by_cid.items()}
    defn_of = {v['submissionValue']: (v.get('definition') or '')
               for v in cd_by_cid.values()}

    req, fda = required_from_rules(rules)

    if a.required:
        print(f'\n=== 必須の TSPARMCD（CORE-000740 / CDISC CG0287）: {len(req)} 種 ===')
        for w in req:
            print(f'  {w:10} {parm_of.get(w, "(CT に無い)"):46} {defn_of.get(w, "")[:60]}')
        print(f'\n=== STYPE=INTERVENTIONAL のとき揃える組（CORE-000741 / FDA FB1111）: '
              f'{len(fda)} 種 ===')
        for w in fda:
            print(f'  {w:10} {parm_of.get(w, "(CT に無い。自由文)"):46} {defn_of.get(w, "")[:60]}')

    if a.values:
        print('\n=== 値に CT を使うパラメータの選択肢 ===')
        for parm, clname in VALUE_CODELISTS.items():
            c, t = ct_terms(codelists, clname)
            if c is None:
                print(f'  {parm:10} codelist {clname} が CT に無い')
                continue
            vals = [x['submissionValue'] for x in t]
            print(f'  {parm:10} （codelist {clname}: {c.get("name")}） {len(vals)} 値')
            print(f'{"":13}{", ".join(vals)}')

    if a.domains:
        varmeta = load(a.cache, 'variables_metadata.pkl')
        key = f'library_variables_metadata/sdtmig/{a.ig}'
        if key not in varmeta:
            raise SystemExit(f'{key} がキャッシュにありません')
        ig = varmeta[key]
        print(f'\n=== Trial Design ドメインの変数（IG {a.ig}）===')
        for dom in TD_DOMAINS:
            if dom not in ig:
                print(f'  {dom}: IG に無い')
                continue
            vs = [(k, v) for k, v in ig[dom].items() if isinstance(v, dict)]
            vs.sort(key=lambda kv: int(kv[1].get('ordinal') or 999))
            print(f'  {dom} : {len(vs)} 変数')
            for k, v in vs:
                print(f'{"":8}{k:12} {v.get("core") or "":5} {v.get("role") or "":20} '
                      f'{(v.get("label") or "")[:44]}')

    if a.skeleton:
        print('\n=== ts.csv の骨組み（必須パラメータ。tsval を埋める）===')
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator='\n')
        w.writerow(['tsparmcd', 'tsparm', 'tsseq', 'tsval', 'tsvalnf', 'source'])
        for p in req + [x for x in fda if x not in req]:
            w.writerow([p, parm_of.get(p, ''), 1, '', '', ''])
        print(buf.getvalue(), end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
