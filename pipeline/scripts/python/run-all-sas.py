# run-all-sas.py
#
# SAS 側の解析を受領CSVから図表まで一続きで回す。実行の順序はここが正本。
#
#   python scripts/run-all-sas.py                    ... UTF-8 セッション（既定）
#   python scripts/run-all-sas.py --encoding sjis    ... 従来の shift-jis セッション
#   python scripts/run-all-sas.py --only ARD,TLF_ja  ... 一部だけ回す（タグは下の STEPS が持つ）
#   python scripts/run-all-sas.py --log-dir <dir>    ... ログの置き場を変える
#   python scripts/run-all-sas.py --root <dir>       ... 入出力を別の試験フォルダへ振り替える
#   python scripts/run-all-sas.py --no-gate          ... 品質検査の停止条件を外して通す
#
# Dataset-JSON の後処理（BOM 除去・JSON として読めることの確認）と define.xml の更新・
# CORE 検証は含まない。それぞれ run-adam-json.py・run-sdtm-validation.py が持つ。
#
# 前提：受領CSVが Box の input/rawdata 直下に展開されていること。
import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath  # noqa: E402
import runcommon  # noqa: E402

REPO = runcommon.REPO
SCRIPTS = os.path.join(REPO, 'scripts')

# 試験 ID は docs/metadata/trial.json だけが持つ。プログラム名の組み立てに使い、
# 試験名をこのファイルへ書かない（boxpath.trial_id）。
TRIAL = boxpath.trial_id()


def prog(name, qc=False):
    """program/sas 配下の SAS プログラム。名前は <試験ID>_<段階>.sas で組み立てる"""
    parts = ['program', 'sas'] + (['qc'] if qc else []) + ['%s_%s.sas' % (TRIAL, name)]
    return os.path.join(*parts)


# 実行の順序。ARD の後に ARDtoCards、ADaM の後に JSON という依存があるので並べ替えない。
# 品質検査（QC）は ADaM の後、ARD より前に置く。ADaM に論理矛盾があるまま
# 図表まで作ってしまうと、出来上がった図表を見て初めて気づくことになる。gate を持つ段階は
# ログに該当パターンが出たらそこで止める（調べるだけなら --no-gate で外す）。パターンは行頭に
# 錨を打つ。SAS のログはソースをエコーするので、%put の書かれた行そのものが引っかかる
# （2026-08-24 に QC03 のゲートが不一致0でも止まった）。
# 停止条件の印は「WARNING: [QCnn] 停止条件」で全本に共通の形にしてある。QC 側が期待値を
# 持たず docs/metadata の宣言と突き合わせるので、ここに件数は書かない。
#
# QC の並びは試験ごとに書き換える。何を検算するか（生存時間の検算表との突合、疾患固有の
# 判定規則、症例報告書の入力規則）は疾患と統計解析計画書で変わるため、汎用層は段階の置き場と
# 停止条件の形だけを持つ。下の4本は試験A の並びで、新しい試験では番号・名前ごと差し替える。
STEPS = [
    {'tag': 'CSVtoSDTM',  'program': prog('CSVtoSDTM')},
    {'tag': 'SDTMtoADaM', 'program': prog('SDTMtoADaM')},
    {'tag': 'QC01', 'program': prog('QC01_RawDataScan', qc=True),
     'gate': r'^WARNING: \[QC01\] 停止条件'},
    {'tag': 'QC03', 'program': prog('QC03_TTECheck', qc=True),
     'gate': r'^WARNING: \[QC03\] 停止条件'},
    {'tag': 'QC04', 'program': prog('QC04_CMRCheck', qc=True),
     'gate': r'^WARNING: \[QC04\] 停止条件'},
    {'tag': 'QC05', 'program': prog('QC05_CCyRRuleCheck', qc=True),
     'gate': r'^WARNING: \[QC05\] 停止条件'},
    {'tag': 'ARD', 'program': prog('ARD'),
     'wait_for': os.path.join('datasets', 'sas', 'ard', 'ard.sas7bdat')},
    {'tag': 'ARDtoCards', 'program': prog('ARDtoCards')},
    # 図表は output/tlf/sas-<lang>/ に出る（TLF.sas の既定で tlfhtml=1）。R 側は
    # output/tlf/r-<lang>/ なので系統でディレクトリが分かれ、名前が衝突しない。
    # トレーサビリティ索引と PI パッケージが読むのは R 側である
    {'tag': 'TLF_ja', 'program': prog('TLF'), 'init_stmt': '%let lang=ja;'},
    {'tag': 'TLF_en', 'program': prog('TLF'), 'init_stmt': '%let lang=en;'},
    {'tag': 'ADaMtoMaster', 'program': prog('ADaMtoMaster')},
    {'tag': 'SDTMtoJSON',   'program': prog('SDTMtoJSON')},
    {'tag': 'ADaMtoJSON',   'program': prog('ADaMtoJSON')},
]


def main():
    runcommon.setup_console()
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('--encoding', choices=['utf8', 'sjis'], default='utf8')
    ap.add_argument('--root')
    ap.add_argument('--log-dir')
    # ssh 経由（run-remote-sas.sh 越し）で呼ぶと 1本の文字列として届く。値をコンマで
    # 割ることで、ローカル起動とリモート起動を同じ形で扱う（2026-08-23 に実測。
    # リモートから -Only を渡すと該当0件で落ちていた）
    ap.add_argument('--only')
    ap.add_argument('--no-gate', action='store_true')
    args = ap.parse_args()

    # --root を渡すと、入力・出力・ログの置き場をまとめてその下へ振り替える。本番の試験
    # フォルダを読み書きせずに検証するための口で、autoexec.sas・runcommon.py・R 側の
    # ap_root() の3つが同じ場所を指すように環境変数を1つ立てる
    # （docs/records/mac-sas-r-verification-plan-20260823.md）。SAS は子プロセスとして
    # 環境変数を継承するので、これで autoexec に届く。
    # 2026-08-29 まで試験ごとの名前（<試験ID>_ROOT）も併せて立てていたが、名前の組み立て方が
    # 枠組みと試験側で食い違っており、2試験目で黙って空振りする形だった。名前は1つにする。
    if args.root:
        if not os.path.isdir(args.root):
            raise SystemExit('--root が指す場所がありません: %s' % args.root)
        os.environ['AKIKO_TRIAL_ROOT'] = os.path.abspath(args.root)
        print('出力先の差し替え（検証用）: %s' % os.environ['AKIKO_TRIAL_ROOT'])

    box = runcommon.trial_root()

    steps = STEPS
    only_set = []
    if args.only:
        only_set = [s for s in args.only.replace(' ', ',').split(',') if s]
        steps = [s for s in STEPS if s['tag'] in only_set]
        if not steps:
            raise SystemExit('--only に該当する段階がありません（指定: %s）'
                             % '、'.join(only_set))

    print('SAS セッションの符号化: %s' % args.encoding)
    print('Box: %s' % box)
    results = []
    t0 = time.monotonic()

    enc = runcommon.resolve_encoding(args.encoding)
    for s in steps:
        r = runcommon.invoke_sas(os.path.join(REPO, s['program']), s['tag'],
                                 log_dir=args.log_dir, init_stmt=s.get('init_stmt'),
                                 encoding=args.encoding)
        results.append(r)
        if s.get('gate'):
            lines = runcommon.read_log(r['log'], enc)
            hit = runcommon.count_matches(lines, s['gate'])
            if hit:
                for ln in hit[:3]:
                    print('  %s' % ln)
                if args.no_gate:
                    print('  （%s: 停止条件に触れたが --no-gate のため続けます）' % s['tag'])
                else:
                    raise SystemExit('%s が停止条件に触れました。直してから通すこと'
                                     '（ログ %s）。調べるだけなら --no-gate' % (s['tag'], r['log']))
        if s.get('wait_for'):
            runcommon.wait_box_file(os.path.join(box, s['wait_for']))

    # ARS の ReportingEvent。パイプラインの部品ではなく末端から枝分かれする成果物なので、
    # 段階の一覧には入れず最後に1度だけ作る。--only で一部だけ回したときは ARD が古い可能性が
    # あるので作らない（pipeline/cdisc-ars.md「ARS を採るかどうかの判断軸」）。
    if not args.only:
        print('')
        print('ARS の ReportingEvent')
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'build-ars-json.py')],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace')
        for ln in (p.stdout + p.stderr).splitlines():
            print('  %s' % ln)
        # 終了コードを見る。見ないと生成の失敗が画面から消える（2026-09-05 に
        # update-define-xml の失敗が同じ理由で消えていた）
        if p.returncode != 0:
            raise SystemExit('ReportingEvent の生成が失敗しました（終了コード %d）'
                             % p.returncode)
    elif 'ARD' in only_set or 'ARDtoCards' in only_set:
        # ARD を作り直したのに ReportingEvent が古いままだと、両系統の突合が版のずれを
        # 不一致として報告する。作らない設計は保ったまま、作り直しが要ることを知らせる
        print('')
        print('  注意: ARD を作り直したので ReportingEvent が古いままです。')
        print('        python scripts/build-ars-json.py --system sas で作り直してください。')

    minutes = round((time.monotonic() - t0) / 60, 1)
    e = sum(r['error'] for r in results)
    w = sum(r['warning'] for r in results)
    print('')
    print('完了: %d 段階  ERROR %d  WARNING %d  所要 %s 分' % (len(results), e, w, minutes))


if __name__ == '__main__':
    try:
        main()
    except runcommon.SasError as exc:
        print(str(exc))
        sys.exit(1)
