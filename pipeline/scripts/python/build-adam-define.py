# build-adam-define.py
#
# ADaM の define.xml（Define-XML 2.0.0）を作る。生成の本体はスキル cdisc-define-xml の
# scripts/build-adam-define.py にあり、ここが持つのは材料の在処と、試験の情報を
# docs/metadata/trial.json から渡す配線だけ。2026-08-20 に他の試験でも使えるよう
# 汎用化してスキルへ移した。試験名・説明文をこのファイルへ書かない。
#
#   変数と型・行数         : Box datasets/r/adam/json/*.json（SDTMtoADaM.R の出力）
#   ラベル・宣言長・並び・Origin・Predecessor : docs/metadata/variable-map.csv（手で維持する正本）
#   ItemRef/@Mandatory     : docs/metadata/external/adamig-1-1-variables.csv（ADaM IG 1.1 の Core）
#   CodeList               : docs/metadata/adam-codelist.csv（ADaM は受領 define.xml が無いので
#                            値と Decode の両方をこの CSV が持つ）
# 出力 : Box datasets/define/adam/define.xml と define2-0-0.xsl（SDTM 側の XSL をそのまま使う）
#
# 実行 : python scripts/build-adam-define.py
#        python scripts/build-adam-define.py --compare <xml>  ... 作らずに突き合わせる
#        スキルの置き場所は環境変数 CDISC_DEFINE_XML_SKILL で差し替えられる。
#
# 通しで回すときは scripts/run-adam-validation.py が、宣言と実データの照合のあとにこれを
# 呼ぶ。単独で回すと照合を経ないので、宣言が実データと食い違ったまま define.xml が出来る。
#
# 言語は英語のみ。日本語は docs/metadata/label-catalog.csv と PI 用 HTML が持つ
# （docs/reporting/traceability-design.md「define.xml の方針」）。
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath  # noqa: E402

sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.environ.get('USERPROFILE') or os.path.expanduser('~')
# 試験フォルダと試験 ID は docs/metadata/trial.json だけが持つ（boxpath.py）
BOX = boxpath.trial_dir()
TRIAL = boxpath.trial_id()
# 入力は R 系の Dataset-JSON（2026-09-05、段C）。出力先は実装系統を持たない
# datasets/define/<層>
SRC = os.path.join(BOX, 'datasets', 'r', 'adam')
ADS = os.path.join(BOX, 'datasets', 'define', 'adam')


def define_meta(key):
    """define.xml の見出しに載る試験の情報。trial.json の define ブロックが正本。

    値を伏せ字にしてスクリプトへ残さない。埋まっていなければ何が足りないかを言って止まる。
    ここで既定値を与えると、別の試験の説明文を載せた define.xml が黙って出来る。
    """
    d = (boxpath.config().get('define') or {})
    v = (d.get(key) or '').strip()
    if not v:
        raise SystemExit('\n'.join([
            f'trial.json の define.{key} が空です。',
            '次の形で埋める:',
            '  "define": {"study_description": "<試験の説明（英語）>",',
            '              "protocol_name": "<研究計画書の名称>",',
            '              "originator": "<作成者（データセンター・解析担当）>"}',
        ]))
    return v

ap = argparse.ArgumentParser()
ap.add_argument('--json-dir', help='ADaM の Dataset-JSON（既定 Box の datasets/r/adam/json）')
ap.add_argument('--out-dir', help='define.xml の書き出し先（既定 Box の datasets/define/adam）')
ap.add_argument('--compare', help='作った define.xml をこのファイルと突き合わせる'
                                  '（CreationDateTime を除いて比べる）。このとき書き出し先は'
                                  '一時フォルダになり、既定の置き場は書き換えない')
a = ap.parse_args()

json_dir = a.json_dir or os.path.join(SRC, 'json')
# --compare は「いま宣言と実データから作るとどうなるか」を見るためのものなので、
# 突き合わせる相手を作り直しで上書きしない。SDTM 側の update-define-xml.py が
# --out-dir と --compare を別に持つのと同じ扱いにする。
tmp = tempfile.mkdtemp(prefix='adam-define-') if a.compare else None
out_dir = tmp or a.out_dir or ADS
os.makedirs(out_dir, exist_ok=True)
out_xml = os.path.join(out_dir, 'define.xml')

SKILL = os.environ.get('CDISC_DEFINE_XML_SKILL',
                       os.path.join(HOME, '.claude', 'skills', 'cdisc-define-xml'))
BUILDER = os.path.join(SKILL, 'scripts', 'build-adam-define.py')
if not os.path.exists(BUILDER):
    raise SystemExit(f'スキルの生成スクリプトがありません: {BUILDER}\n'
                     '（CDISC_DEFINE_XML_SKILL でスキルの場所を指定できます）')

ARGS = [
    '--json-dir', json_dir,
    '--variable-map', os.path.join(REPO, 'docs', 'metadata', 'variable-map.csv'),
    '--adam-ig', os.path.join(REPO, 'docs', 'metadata', 'external', 'adamig-1-1-variables.csv'),
    '--codelist', os.path.join(REPO, 'docs', 'metadata', 'adam-codelist.csv'),
    '--out', out_xml,
    '--study-oid', TRIAL,
    '--study-name', TRIAL,
    '--study-description', define_meta('study_description'),
    '--protocol-name', define_meta('protocol_name'),
    '--mdv-name', 'ADaM Metadata for %s' % TRIAL,
    '--originator', define_meta('originator'),
    '--standard-version', '1.1',
    '--xsl-from', os.path.join(BOX, 'datasets', 'define', 'sdtm', 'define2-0-0.xsl'),
]

code = subprocess.call([sys.executable, BUILDER] + ARGS)
if code or not a.compare:
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(code)

# 突き合わせ。CreationDateTime だけは回ごと（日ごと）に変わるので、その属性を伏せてから
# 1バイトずつ比べる。違えば非0で終える。宣言や実データが変わったのに define.xml を作り
# 直していない状態は、ここで初めて機械の目に触れる（2026-09-05 に ABLMUTFL の def:Origin が
# 古いまま納品パッケージへ入りかけた）。
try:
    if not os.path.exists(a.compare):
        raise SystemExit('突き合わせる相手がありません: %s' % a.compare)
    stamp = re.compile(r'CreationDateTime="[^"]*"')
    made = stamp.sub('CreationDateTime=""', open(out_xml, 'rb').read().decode('utf-8'))
    have = stamp.sub('CreationDateTime=""', open(a.compare, 'rb').read().decode('utf-8'))
    if made != have:
        print('作り直した define.xml が %s と違います' % a.compare)
        sys.exit(1)
    print('突き合わせ: %s と一致（CreationDateTime を除いて %d バイト）'
          % (a.compare, len(made.encode('utf-8'))))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
