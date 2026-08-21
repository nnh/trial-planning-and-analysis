"""CDISC CORE の検証結果から指摘の内訳を出す。

CORE の JSON は指摘を1行ずつ持つだけで、何が起きているかは集約しないと見えない。
このスクリプトは3つの見方を出す。

  1. ルール別の件数と status（`--report` だけを渡したとき）
  2. 仕分けの状態との突合（`--disposition` を渡すと未仕分けだけを出す）
  3. 1ルールの内訳（`--rule CORE-000914` で、指摘された変数と値の組み合わせを集約）

3 が肝心である。**1つのルールの指摘が複数の原因の混合であることがある。** 実測例では
FA のベースラインフラグの重複261件のうち、166行が CRF の構造（1つの `FAOBJ` に2種類の
観測が入っている）で、95行はルールのグルーピングキーに `FAOBJ` が入らないことによる
偽陽性だった。件数だけを見て一括で判断すると、直せるものと直せないものを取り違える。

`EXECUTION ERROR` のルールも `Issue_Summary` に各1件として現れる。指摘の件数に混ぜると
誤るので `Rules_Report` の `status` で分ける。

    python summarize-core-issues.py --report <日付>-sdtm-validation.json
    python summarize-core-issues.py --report ... --disposition docs/core-issue-disposition.csv
    python summarize-core-issues.py --report ... --rule CORE-000914 [--examples 10]
"""
import argparse
import collections
import csv
import json
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def load_report(path):
    with open(path, encoding='utf-8') as f:
        j = json.load(f)
    status = {r['core_id']: r['status'] for r in j.get('Rules_Report', [])}
    msg = {r['core_id']: r.get('message') or '' for r in j.get('Rules_Report', [])}
    count = collections.Counter()
    dsets = collections.defaultdict(set)
    for s in j.get('Issue_Summary', []):
        count[s['core_id']] += s.get('issues') or 0
        if s.get('dataset'):
            dsets[s['core_id']].add(str(s['dataset']))
    return j, status, msg, count, dsets


def load_disposition(path):
    d = {}
    if not path:
        return d
    if not os.path.exists(path):
        raise SystemExit(f'仕分けの CSV がありません: {path}')
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            d[r['core_id']] = r
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--report', required=True, help='CORE の出力 JSON')
    ap.add_argument('--disposition', help='仕分けの CSV（core_id,disposition,note,ref）')
    ap.add_argument('--rule', help='内訳を詳しく見るルール（CORE-000914 など）')
    ap.add_argument('--examples', type=int, default=6, help='値の組み合わせの表示数（既定6）')
    a = ap.parse_args()

    j, status, msg, count, dsets = load_report(a.report)
    disp = load_disposition(a.disposition)

    print(f'{os.path.basename(a.report)}')
    st = collections.Counter(status.values())
    for k in ('SUCCESS', 'SKIPPED', 'ISSUE REPORTED', 'EXECUTION ERROR'):
        if k in st:
            print(f'  {k:16} {st[k]}')

    # ---- 1ルールの内訳 ----
    if a.rule:
        rid = a.rule
        det = [d for d in j.get('Issue_Details', []) if d.get('core_id') == rid]
        print(f'\n== {rid} ==')
        print(f'  status  : {status.get(rid, "(Rules_Report に無い)")}')
        print(f'  message : {msg.get(rid, "")}')
        print(f'  Issue_Details : {len(det)} 行')
        if not det:
            print('  内訳を出せない（この JSON に詳細が無い）')
            return 0
        print(f'  データセット: {dict(collections.Counter(str(d.get("dataset")) for d in det).most_common())}')
        combo = collections.Counter()
        for d in det:
            pairs = tuple(zip(d.get('variables') or [],
                              [str(v)[:44] for v in (d.get('values') or [])]))
            combo[pairs] += 1
        print(f'  変数と値の組み合わせ: {len(combo)} 通り')
        for cb, n in combo.most_common(a.examples):
            print(f'    {n:6} 件  ' + ' | '.join(f'{k}={v}' for k, v in cb))
        if len(combo) > a.examples:
            print(f'    ... 他 {len(combo) - a.examples} 通り')
        subj = collections.Counter(d.get('USUBJID') for d in det if d.get('USUBJID'))
        if subj:
            print(f'  症例数: {len(subj)}（最多 {subj.most_common(1)[0][1]} 件/症例）')
        # 指摘がドメインの全行と一致していないか
        for ds in j.get('Dataset_Details', []):
            if str(ds.get('filename')).upper() in {str(d.get('dataset')).upper() for d in det}:
                if ds.get('length') == len(det):
                    print(f'  注意: 指摘 {len(det)} 件が {ds.get("filename")} の全行数と一致する。'
                          'データの欠陥ではなくルールの前提を疑う')
        return 0

    # ---- ルール別の一覧 ----
    issue = [(k, v) for k, v in count.items() if status.get(k) != 'EXECUTION ERROR']
    execerr = [k for k, v in count.items() if status.get(k) == 'EXECUTION ERROR']
    issue.sort(key=lambda x: -x[1])

    if disp:
        known = [(k, v) for k, v in issue if disp.get(k, {}).get('disposition') == 'known']
        rest = [(k, v) for k, v in issue if disp.get(k, {}).get('disposition') != 'known']
        print(f'\n既知として残すと決めた指摘 : {len(known)} ルール / {sum(v for _, v in known):,} 件')
        for k, v in known:
            print(f'  {v:7,} 件  {k}  {disp[k].get("note", "")}')
        print(f'\n未仕分け : {len(rest)} ルール / {sum(v for _, v in rest):,} 件')
        for k, v in rest:
            d = ','.join(sorted(dsets.get(k, [])))
            print(f'  {v:7,} 件  {k}  [{d}]  {msg.get(k, "")[:100]}')
        if rest:
            print(f'\n内訳を見る: --rule {rest[0][0]}')
    else:
        print(f'\n指摘のあるルール : {len(issue)} / 合計 {sum(v for _, v in issue):,} 件')
        for k, v in issue:
            d = ','.join(sorted(dsets.get(k, [])))
            print(f'  {v:7,} 件  {k}  [{d}]  {msg.get(k, "")[:100]}')

    if execerr:
        print(f'\nルールが実行できなかったもの : {len(execerr)} ルール'
              '（Issue_Summary に各1件として現れるが指摘ではない）')
        for k in execerr:
            print(f'  {k}  {msg.get(k, "")[:100]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
