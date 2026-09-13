# rebuild-ars.py
#
# 納品パッケージの中で ARS の ReportingEvent（reporting-event-r.json）を作り直す。図表を
# 作り直したときに、解析の定義と結果値を CDISC の標準形式でも同じ状態へ更新するために使う。
#
# ReportingEvent そのものを作るのは隣の build-ars-json.py で、こちらはその薄い包みである。
# 宣言と受入基準はパッケージでもリポジトリと同じ相対位置（docs/metadata・
# docs/validation/acceptance）に置いてあるので、生成はその場のまま読める。違うのは結果値
# （ARD）の置き場だけで、パッケージでは ../data/ard/、生成が読むのは試験フォルダの
# datasets/r/ard/ である。そこで ARD だけを一時フォルダへ写し、AKIKO_BOX_ROOT でそこを
# 見せて呼ぶ。写しは終わったら消す。ファイルを書き換えず、探し方だけで吸収する。
#
# 2026-08-31 まで、宣言と trial.json も一時フォルダへ組み直していた。パッケージが仕様を
# input/spec/ へ平らに写していたためで、その平坦化をやめたので組み直しも要らなくなった。
#
# 作り直したものが納品したものと同じかは、隣の compare-ars-json.py で確かめられる。
#   python scripts/compare-ars-json.py --a ../16_1_9_methods/reporting-event-r.json --b <作り直したもの>
#
# このファイルはパッケージの中（reproduce/scripts/）で動かすためのもので、リポジトリ側で
# 直接呼ぶものではない。リポジトリでは build-ars-json.py をそのまま呼べばよい。
#
# 使い方（パッケージの reproduce/ を起点に）
#   python scripts/rebuild-ars.py
#   python scripts/rebuild-ars.py --out <出力先の json>
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))     # reproduce/scripts
REP = os.path.dirname(HERE)                           # reproduce
PKG = os.path.dirname(REP)                            # パッケージの直下

sys.stdout.reconfigure(encoding='utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(PKG, '16_1_9_methods',
                                                  'reporting-event-r.json'),
                    help='ReportingEvent の出力先（既定は納品時と同じ場所）')
    a = ap.parse_args()

    cfg_path = os.path.join(REP, 'docs', 'metadata', 'trial.json')
    if not os.path.isfile(cfg_path):
        raise SystemExit('試験の設定が無い: ' + cfg_path)
    cfg = json.load(open(cfg_path, encoding='utf-8'))
    rel = cfg.get('box_path')
    if not rel:
        raise SystemExit('trial.json に box_path がない: ' + cfg_path)

    # 結果値。納品するのは R 系なので、作り直しも R 系の ARD を読む
    src = os.path.join(PKG, 'data', 'ard', 'ard_cards_r.csv')
    if not os.path.exists(src):
        raise SystemExit('結果値が無い: data/ard/ard_cards_r.csv')

    work = tempfile.mkdtemp(prefix='ars-')
    try:
        d = os.path.join(work, 'box', *rel, 'datasets', 'r', 'ard')
        os.makedirs(d)
        shutil.copy2(src, os.path.join(d, 'ard_cards_r.csv'))
        print('作業用の写し: 結果値 1 組', flush=True)
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, 'build-ars-json.py'),
             '--system', 'r', '--out', a.out],
            env=dict(os.environ, AKIKO_BOX_ROOT=os.path.join(work, 'box')))
        if r.returncode:
            raise SystemExit('ReportingEvent の生成が失敗した（終了コード %d）'
                             % r.returncode)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print('できた: ' + a.out)


if __name__ == '__main__':
    main()
