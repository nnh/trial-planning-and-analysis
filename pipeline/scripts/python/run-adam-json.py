# run-adam-json.py
#
# ADaM の Dataset-JSON を作る。
#   1. <試験ID>_ADaMtoJSON.sas を実行
#   2. BOM を除去（SAS の file encoding='utf-8' は BOM を書く）
#   3. 生成された全ファイルが JSON として読めることを確認
#
# 前提：ADaM データセットが Box の datasets/sas/adam に出来ていること
#       （program/sas/<試験ID>_SDTMtoADaM.sas を先に実行する）
#       SDTM 側の同じ処理は scripts/run-sdtm-validation.py が持つ。
#
# 使い方：python scripts/run-adam-json.py
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath  # noqa: E402
import runcommon  # noqa: E402

BOM = b'\xef\xbb\xbf'


def strip_bom(json_dir):
    """SAS の encoding='utf-8' は BOM を書き出すが、jsonlite は BOM 付きを警告する。
    SDTM 側（run-sdtm-validation.py）と同じく除去して揃える。
    """
    n = 0
    for path in sorted(glob.glob(os.path.join(json_dir, '*.json'))):
        with open(path, 'rb') as f:
            data = f.read()
        if data.startswith(BOM):
            with open(path, 'wb') as f:
                f.write(data[len(BOM):])
            n += 1
    return n


def main():
    runcommon.setup_console()
    ap = argparse.ArgumentParser()
    ap.add_argument('--encoding', choices=['utf8', 'sjis'], default='utf8')
    args = ap.parse_args()

    repo = runcommon.REPO
    box = runcommon.trial_root()
    json_dir = os.path.join(box, 'datasets', 'sas', 'adam', 'json')

    # 試験 ID は docs/metadata/trial.json だけが持つ。プログラム名の組み立てに使う
    trial = boxpath.trial_id()

    print('1. Dataset-JSON の生成')
    runcommon.invoke_sas(
        os.path.join(repo, 'program', 'sas', '%s_ADaMtoJSON.sas' % trial),
        '%s_ADaMtoJSON' % trial, encoding=args.encoding)

    print('2. BOM の除去')
    print('   %d ファイルから除去' % strip_bom(json_dir))

    # 空ラベルを put の "&&vb&i" に埋めると SAS が引用符をエスケープと解釈して
    # 不正な JSON になる（2026-08-19 に発覚）。ERROR が出ないので、読めることを必ず確かめる。
    print('3. JSON として読めるかの確認')
    ng = []
    for path in sorted(glob.glob(os.path.join(json_dir, '*.json'))):
        name = os.path.basename(path)
        try:
            with open(path, encoding='utf-8') as f:
                d = json.load(f)
            print('   %-12s columns %3d / records %6s'
                  % (name, len(d.get('columns') or []), d.get('records')))
        except (OSError, ValueError) as exc:
            ng.append(name)
            print('   %s : 読めません — %s' % (name, exc))
    if ng:
        raise SystemExit('不正な JSON: %s' % ', '.join(ng))
    print('完了。%s' % json_dir)


if __name__ == '__main__':
    try:
        main()
    except runcommon.SasError as exc:
        print(str(exc))
        sys.exit(1)
