# check-environment.py
#
# 試験を立ち上げる前に、この端末で何が回せて何が回せないかを一度に見る。
#
# なぜ要るか。枠組みのスクリプトは、処理系・CDISC CORE・スキルの置き場を
# 環境変数か既定のパスから引く。引けないことが分かるのは、その段を回した時点である。
# 立ち上げの手順を上から実行していくと、ディレクトリを作り、雛形を写し、資料を集めた後で
# 「CORE が無いので SDTM の検証が回せない」と分かる。依存の不足は、データを作り始める前に
# まとめて出す。
#
# 立案の端末だけでなく、解析を回す端末の要件も見る。実行の入口を移したときに実行機の側が
# 追随せず、16日後に初めてリモートで回して5つの不足に一度に突き当たったことがある
# （findings/analysis-findings-log.md「実行の入口を移したとき、実行機の側が追随しない」）。
#
# 試験のリポジトリが無くても動く。試験の設定（trial.json）も Box も読まない。
#
# 使い方
#   python3 pipeline/scripts/python/check-environment.py
#   python3 pipeline/scripts/python/check-environment.py --framework <この枠組みのパス>
#
# 終了コード 0 必須がそろっている / 1 必須が欠けている / 2 検査自体が走らなかった
import argparse
import importlib.util
import os
import shutil
import subprocess
import sys

HOME = os.environ.get('USERPROFILE') or os.path.expanduser('~')

# 環境変数で置き場を変えられるもの。既定は導入手順が置く場所
ENV_KEYS = {
    'SAS_HOME': 'SAS の導入先',
    'CDISC_CORE_EXE': 'CDISC CORE の実行ファイル',
    'CDISC_DEFINE_XML_SKILL': 'cdisc-define-xml スキルの置き場',
    'TRIAL_REVIEW_DIR': '枠組みの review/ の置き場',
    'PLAYWRIGHT_BROWSERS_PATH': 'playwright が入れたブラウザの置き場',
}


def which(name):
    return shutil.which(name)


def has_module(name):
    """この検査を走らせている処理系で import できるか。

    別の python を呼んで確かめない。検査スクリプトもこの処理系で動くので、
    ここで見えないものはそちらでも見えない。PATH に複数の python が居る端末で、
    入っている方を見て「有る」と報告するのを避ける。
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def chromium_dir():
    """playwright が落としたブラウザを探す。

    パッケージだけ入れて `playwright install chromium` を回していない端末がある。
    その状態でも import は通るので、パッケージの有無だけでは足りない。
    既定の置き場は OS ごとに違い、PLAYWRIGHT_BROWSERS_PATH で変えられる。
    """
    env = os.environ.get('PLAYWRIGHT_BROWSERS_PATH')
    cands = [env] if env else [
        os.path.join(HOME, 'AppData', 'Local', 'ms-playwright'),
        os.path.join(HOME, 'Library', 'Caches', 'ms-playwright'),
        os.path.join(HOME, '.cache', 'ms-playwright'),
    ]
    for d in cands:
        if not d or not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.startswith('chromium-'):
                return os.path.join(d, name)
    return None


def version(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    out = (p.stdout or '') + (p.stderr or '')
    return out.strip().splitlines()[0] if out.strip() else ''


def check(rows, need, name, ok, detail, lost):
    """1件を積む。ok が False のとき、need なら必須の欠落として数える。"""
    rows.append({'need': need, 'name': name, 'ok': ok, 'detail': detail, 'lost': lost})


def main():
    p = argparse.ArgumentParser(description='立ち上げ前の環境の一括検査')
    p.add_argument('--framework', help='この枠組みの作業コピー（既定はこのスクリプトの位置から辿る）')
    a = p.parse_args()

    # このスクリプトは <枠組み>/pipeline/scripts/python/ にある
    here = os.path.abspath(__file__)
    fw = a.framework or os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(here))))
    rows = []

    check(rows, True, 'python3', sys.version_info >= (3, 8),
          sys.version.split()[0], '枠組みのスクリプトが動かない')
    check(rows, True, 'git', bool(which('git')), which('git') or '',
          '版を固定できず、再現の確認ができない')

    r = which('Rscript')
    check(rows, True, 'R（Rscript）', bool(r), version(['Rscript', '--version']) or r or '',
          'R 系の生成が回せない。二重コーディングの片系統が作れない')

    # R から make が見えるか。CRAN に版に対応するバイナリが無いパッケージは
    # ソースからのビルドになるので、これが無いと renv の復元が途中で止まる。
    # Windows は Rtools、macOS は Xcode のコマンドラインツールが make を持つ。
    # 見ているのは「R から make が見えるか」だけで、ビルドが通ることまでは確かめていない。
    make = version(['Rscript', '-e', 'cat(Sys.which("make"))']) if r else None
    check(rows, False, 'R のビルド道具（make）', bool(make),
          make or ('Rtools（Windows）・xcode-select --install（macOS）' if r
                   else 'R が無いので確かめていない'),
          'CRAN にバイナリが無いパッケージをソースからビルドできない。'
          'renv の復元が途中で止まる')

    sas_home = os.environ.get('SAS_HOME') or r'C:\Program Files\SASHome\SASFoundation\9.4'
    sas_exe = os.path.join(sas_home, 'sas.exe')
    check(rows, False, 'SAS', os.path.isfile(sas_exe), sas_exe,
          'SAS 系の生成が回せない。この端末では R 系だけになるので、'
          '突合はリモート実行か別端末で行う')

    core = os.environ.get('CDISC_CORE_EXE') or os.path.join(
        HOME, 'opt', 'cdisc-core', 'core', 'core.exe')
    check(rows, False, 'CDISC CORE', os.path.isfile(core), core,
          'SDTM の適合性検証が回せない。区間2の出口条件を満たせない')

    # 検査の3本だけが外部パッケージを要る。生成と実行の経路は標準ライブラリで動く
    # （pipeline/README.md「実行できる形」）。無い端末では検査が終了コード2で
    # 「検証できなかった」と返すので、合格と紛れることはないが、回せば止まる。
    check(rows, False, 'jsonschema', has_module('jsonschema'),
          'python -m pip install jsonschema',
          'ReportingEvent を ARS の標準スキーマで検証できない（check-ars-json.py）')

    pw = has_module('playwright')
    in_package = os.environ.get('PLAYWRIGHT_BROWSERS_PATH') == '0'
    chrome = chromium_dir() if pw else None
    if not pw:
        pw_detail = 'python -m pip install playwright && playwright install chromium'
    elif chrome:
        pw_detail = chrome
    elif in_package:
        pw_detail = 'パッケージの中に置く指定（PLAYWRIGHT_BROWSERS_PATH=0）。置き場は見ていない'
    else:
        pw_detail = 'パッケージはあるがブラウザが無い（playwright install chromium）'
    check(rows, False, 'playwright', pw and (bool(chrome) or in_package), pw_detail,
          '索引のリンク検査と図表の視覚回帰が回せない（check-traceability.py・'
          'check-visual-regression.py）。成果物の検査の段が通らない')

    skills_dir = os.path.join(HOME, '.claude', 'skills')
    check(rows, True, '~/.claude/skills', os.path.isdir(skills_dir), skills_dir,
          'スキルを写す先が無い。mkdir -p で作る')

    for skill, lost in (
            ('trial-planning-review', '立案時レビューの機械検査が回せない'),
            ('cdisc-define-xml', 'ADaM の define.xml が生成できない')):
        d = os.environ.get('CDISC_DEFINE_XML_SKILL') if skill == 'cdisc-define-xml' else None
        d = d or os.path.join(skills_dir, skill)
        check(rows, True, 'スキル %s' % skill, os.path.isdir(d), d, lost)

    review = os.environ.get('TRIAL_REVIEW_DIR') or os.path.join(fw, 'review')
    check(rows, True, '枠組みの review/', os.path.isdir(os.path.join(review, 'planning-review')),
          review, '立案時レビューの実行器が方法論を見つけられない。'
                  'TRIAL_REVIEW_DIR を指定する')

    width = max(len(x['name']) for x in rows)
    node = os.uname().nodename if hasattr(os, 'uname') else os.environ.get(
        'COMPUTERNAME', '')
    print('端末: %s' % node)
    print('枠組み: %s' % fw)
    print('')
    for x in rows:
        mark = 'OK  ' if x['ok'] else ('欠落' if x['need'] else '無し')
        print('%s %-*s  %s' % (mark, width, x['name'], x['detail']))
        if not x['ok']:
            print('%s %-*s  → %s' % ('    ', width, '', x['lost']))

    print('')
    print('置き場を変えられる環境変数')
    for k, what in ENV_KEYS.items():
        v = os.environ.get(k)
        print('  %-24s %s%s' % (k, what, '（設定あり）' if v else ''))

    miss = [x['name'] for x in rows if x['need'] and not x['ok']]
    opt = [x['name'] for x in rows if not x['need'] and not x['ok']]
    print('')
    if opt:
        print('この端末で回せない工程があります: %s' % '・'.join(opt))
        print('  回せない工程を別端末で回すなら、どちらの端末で何を回すかを'
              '試験側の CLAUDE.md に書く。')
    if miss:
        print('必須が欠けています: %s' % '・'.join(miss))
        print('立ち上げを始める前にそろえること。')
        return 1
    print('必須はそろっています。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
