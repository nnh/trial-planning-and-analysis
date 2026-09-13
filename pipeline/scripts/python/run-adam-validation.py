# run-adam-validation.py
#
# ADaM の define 一式を一続きで作り直す。
#   1. 宣言と実データの照合（variable-map.csv の網羅・宣言長・並び）
#   2. define.xml の更新と HTML 化
#
# SDTM 側の run-sdtm-validation.py と同じ順序である。宣言を実データと突き合わせてから
# 生成し、機械が読む define.xml と人が読む define.html を同じ回で作る。宣言が実データと
# 合っていることを先に見るのは、生成が宣言（variable-map.csv・adam-codelist.csv）を正本と
# して読むためで、照合を経ないと宣言の誤りがそのまま define.xml の誤りになる。
#
# SDTM 側の3段目（CDISC CORE による適合性検証）にあたるものは置いていない。CORE は
# adamig 1-1 のルールセットを持つので技術的に掛けられないわけではないが、掛けると指摘の
# 仕分けの正本（SDTM 側の docs/metadata/core-issue-disposition.csv にあたるもの）が要り、
# それを作るかどうかは統計解析責任者の判断である。判断が済むまでこの入口は照合と生成までに
# する。掛けていないものを掛けているように見せない。
#
# なぜ要るか。2026-09-05 まで ADaM の define.xml を作るのは build-adam-define.py だけで、
# 通し実行の外にあった。ADSL の変数の由来を変えても（ABLMUTFL の predecessor を
# ADSL.ABLMUT から FA.FATESTCD/FA.FASTAT へ直した）define.xml の def:Origin は追随せず、
# 古いものが納品パッケージへ入りかけた。define.html にはそもそも ADaM 側の再生成の経路が
# 無く、2026-09-05 の時点で Box の現物が define.xml より古かった。
#
# 前提：R 系の Dataset-JSON が Box の datasets/r/adam/json に出来ていること
#       （program/r/<試験ID>_SDTMtoADaM.R を先に実行する）
#       生成の本体はスキル cdisc-define-xml にある（build-adam-define.py が呼ぶ）
#
# 使い方：python scripts/run-adam-validation.py
#
# 終了コード 0 全段階が通った / 1 どこかで落ちた
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runcommon  # noqa: E402

REPO = runcommon.REPO
SCRIPTS = os.path.join(REPO, 'scripts')


def call(argv, what):
    """外部プロセスを1本回す。出力はそのまま画面へ流し、失敗したらそこで止める。

    終了コードを見ないと、末尾だけを読んだときに失敗した旨が画面から消える
    （2026-09-05 に run-sdtm-validation で同じ型の見落としが見つかっている）。
    """
    code = subprocess.run(argv, cwd=REPO, check=False).returncode
    if code != 0:
        raise SystemExit('%s が失敗しました（終了コード %d）' % (what, code))


def main():
    runcommon.setup_console()

    print('1. 宣言と実データの照合')
    # 突き合わせ先は R 系の Dataset-JSON にする。define.xml の生成が読むのがそれなので、
    # 別の系統と突き合わせても「生成が読むデータと宣言が合っているか」を見たことにならない。
    call([sys.executable, os.path.join(SCRIPTS, 'check-variable-map.py'), '--system', 'r'],
         '宣言と実データの照合')

    print('2. define.xml の更新')
    call([sys.executable, os.path.join(SCRIPTS, 'build-adam-define.py')],
         'define.xml の生成')

    print('   define.xml の HTML 化')
    # 変換の正本は scripts/build-define-html.R。define.xml を作った同じ回で HTML にする。
    # 別の回に回すと HTML だけが古い状態を作れる（2026-09-05 まで実際にそうなっていた）。
    call([runcommon.find_rscript(),
          os.path.join(SCRIPTS, 'build-define-html.R'), '--layer=adam'],
         'define.html の生成')
    return 0


if __name__ == '__main__':
    sys.exit(main())
