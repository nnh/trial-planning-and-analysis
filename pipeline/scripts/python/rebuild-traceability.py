# rebuild-traceability.py
#
# 納品パッケージの中でトレーサビリティ索引（traceability.html）を作り直す。図表を作り直した
# ときに、索引が持つ解析値と系譜を同じ状態へ更新するために使う。
#
# 索引そのものを作るのは隣の build-traceability.py で、こちらはその薄い包みである。索引生成は
# リポジトリと Box の並び（docs/metadata・docs/tmf/aCRF・datasets・input/rawdata）を読む
# 作りなので、パッケージの並び（../data・input/rawdata・../16_1_2_acrf）をその形へ写した
# 作業用のフォルダを一時的に作り、そこを見せて呼ぶ。写しは終わったら消す。写すだけに
# するのは、同じ宣言と同じデータをパッケージの中に二重に持たないためである。
# 帳票の一覧（docs/tmf/aCRF）はパッケージに無く 16_1_2_acrf/index.html から組み立てるため、
# 宣言が同じ位置にあってもこの包みは要る（rebuild-ars.py はそれが無いので在処だけを渡す）。
#
# このファイルはパッケージの中（reproduce/scripts/）で動かすためのもので、リポジトリ側で
# 直接呼ぶものではない。リポジトリでは build-traceability.py をそのまま呼べばよい。
#
# 使い方（パッケージの reproduce/ を起点に）
#   python scripts/rebuild-traceability.py
#   python scripts/rebuild-traceability.py --out <出力先の html>
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))     # reproduce/scripts
REP = os.path.dirname(HERE)                           # reproduce
PKG = os.path.dirname(REP)                            # パッケージの直下

# 索引生成が docs/metadata から読む宣言。パッケージも同じ位置に置いてある（2026-08-31）
SPEC = ['variable-map.csv', 'crf-field-map.csv', 'crf-option-map.csv',
        'label-catalog.csv', 'tlf-index.csv', 'sdtm_datasets.csv']

# 実値の置き場。左がパッケージの中、右が索引生成が読む Box の並び。索引は納品する図表と
# 同じ R 系の実データを読むので、写す先は datasets/r/ にする。パッケージは層ごとに1組しか
# 持たないため、data/ の中身をそのままそこへ見せる。
DATA = [(('..', 'data', 'sdtm'), ('datasets', 'r', 'sdtm', 'json')),
        (('..', 'data', 'adam'), ('datasets', 'r', 'adam', 'json')),
        (('..', 'data', 'ard'), ('datasets', 'r', 'ard')),
        (('input', 'rawdata'), ('input', 'rawdata'))]

# データセットの定義。索引生成は系統を持たない置き場（datasets/define/<層>）から読む。
# データセットのラベルは docs/metadata/sdtm_datasets.csv が正本なので SPEC の側で渡す
META = [(('..', 'data', 'sdtm', 'define.xml'), ('datasets', 'define', 'sdtm', 'define.xml')),
        (('..', 'data', 'adam', 'define.xml'), ('datasets', 'define', 'adam', 'define.xml'))]


def write_acrf_list(work):
    """帳票の名前と並び順を、索引生成が読む形（*-acrf.csv）で作業用フォルダへ書く。

    パッケージでは 16_1_2_acrf/index.html が帳票の並びを持つので、そこから組み立てる。
    帳票の一覧をパッケージの中に二重に持たないためである。
    """
    src = os.path.join(PKG, '16_1_2_acrf', 'index.html')
    rows = re.findall(r'<li><a href="([^"]+\.html)">([^<]+)</a>',
                      open(src, encoding='utf-8').read())
    d = os.path.join(work, 'docs', 'tmf', 'aCRF')
    os.makedirs(d)
    with open(os.path.join(d, 'package-acrf.csv'), 'w', encoding='utf-8',
              newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        for url, name in rows:
            w.writerow([name, url])
    return len(rows)


def strip_bom(root):
    """写した Dataset-JSON の先頭から BOM を落とす。

    同梱の Dataset-JSON には、表計算でそのまま開けるように BOM が付いているものがある。
    索引生成は JSON を UTF-8 として読むので、BOM が残っていると読み飛ばされ、値レベルの
    条件（PARAMCD・--SPID の実値）が索引に入らない。写した先だけを直すので、パッケージの
    中身には触らない。
    """
    n = 0
    for base, _, files in os.walk(root):
        for f in files:
            if not f.endswith('.json'):
                continue
            p = os.path.join(base, f)
            with open(p, 'rb') as fh:
                body = fh.read()
            if body.startswith(b'\xef\xbb\xbf'):
                with open(p, 'wb') as fh:
                    fh.write(body[3:])
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(PKG, 'traceability.html'),
                    help='索引の出力先（既定はパッケージ直下の traceability.html）')
    a = ap.parse_args()
    cfg = json.load(open(os.path.join(REP, 'docs', 'metadata', 'trial.json'),
                         encoding='utf-8'))
    work = tempfile.mkdtemp(prefix='trace-')
    try:
        os.makedirs(os.path.join(work, 'scripts'))
        for n in ('build-traceability.py', 'traceability_template.html', 'boxpath.py'):
            shutil.copy2(os.path.join(HERE, n), os.path.join(work, 'scripts', n))
        md = os.path.join(work, 'docs', 'metadata')
        os.makedirs(md)
        for n in SPEC:
            shutil.copy2(os.path.join(REP, 'docs', 'metadata', n), os.path.join(md, n))
        # 索引生成は試験の識別子と実値の置き場を trial.json から引く。作業用フォルダの中に
        # 実値を写して見せるので、その中の名前をここで与える（同梱の trial.json は書き換えない）
        cfg['box_path'] = ['data']
        with open(os.path.join(md, 'trial.json'), 'w', encoding='utf-8',
                  newline='\n') as f:
            f.write(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n')
        n_sheet = write_acrf_list(work)
        for src, dst in DATA:
            s = os.path.join(REP, *src)
            if os.path.isdir(s):
                shutil.copytree(s, os.path.join(work, 'box', 'data', *dst))
        for src, dst in META:
            s = os.path.join(REP, *src)
            if os.path.exists(s):
                d = os.path.join(work, 'box', 'data', *dst)
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(s, d)
        n_bom = strip_bom(os.path.join(work, 'box'))
        print('作業用の写し: 帳票 %d、宣言 %d、実値 %d 組、定義 %d 件（BOM を外した JSON %d）'
              % (n_sheet, len(SPEC), len(DATA), len(META), n_bom), flush=True)
        r = subprocess.run(
            [sys.executable, os.path.join(work, 'scripts', 'build-traceability.py'),
             '--out', a.out, '--acrf-base', '16_1_2_acrf', '--tlf-base', '14_tlf/ja'],
            env=dict(os.environ, AKIKO_BOX_ROOT=os.path.join(work, 'box')))
        if r.returncode:
            raise SystemExit('索引の生成が失敗した（終了コード %d）' % r.returncode)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print('できた: ' + a.out)
    print('この包みは索引だけを作り直す。JavaScript が動かないときの静的な入口（noscript の'
          '案内と footer のリンク）は納品時に足したもので、作り直した索引には入らない。')


if __name__ == '__main__':
    main()
