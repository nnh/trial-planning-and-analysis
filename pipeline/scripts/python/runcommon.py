# runcommon.py
#
# run-*.py が共通で使う起動の作法。実行する側から import して使う。
# SAS のバッチ起動と成否の判定、試験フォルダの解決、Rscript の在処、画面の符号化。
#
#   import runcommon
#   runcommon.invoke_sas(os.path.join(repo, 'program', 'sas', '%s_ARD.sas' % trial), 'ARD')
#
# 試験 ID は書かない。呼ぶ側が boxpath.trial_id() で引く（docs/metadata/trial.json が正本）。
#
# セッションの符号化は UTF-8 を既定にする（2026-08-21）。SAS 9.4 の日本語版は既定の
# config が shift-jis のため、Unicode サーバーの config（nls\u8\sasv9.cfg）を -config で
# 明示して起動する。この config は導入済みで、追加のインストールは要らない。
# 従来の shift-jis で回すときだけ encoding='sjis' を渡す（符号化の前後比較に使う）。
#
# sas.exe は GUI サブシステムのアプリだが、subprocess はプロセスハンドルを待つので
# 呼び出しは同期になる（PowerShell の呼び出し演算子が待たずに戻るのとは違い、
# Start-Process -Wait に相当する明示の指定は要らない）。引数はリストで渡す。
# subprocess が空白を含む要素だけを引用符で包むので、-initstmt "%let lang=ja;" が
# 空白で分割されて SAS が異常終了する事故（終了コード116）は起きない。
#
# 2026-09-05 に scripts/sas-common.ps1 から移した。移した理由と、移植の前後で振る舞いが
# 同じであることの確かめ方は pipeline/analysis-pipeline-plan.md「実行できる形を Python と
# R に限る」「別の処理系へ移すときの確かめ方」。
import os
import re
import shutil
import subprocess
import sys
import time

SAS_HOME = r'C:\Program Files\SASHome\SASFoundation\9.4'
SAS_EXE = os.path.join(SAS_HOME, 'sas.exe')
SAS_CONFIG = {
    'utf8': os.path.join(SAS_HOME, 'nls', 'u8', 'sasv9.cfg'),
    'sjis': os.path.join(SAS_HOME, 'nls', 'ja', 'sasv9.cfg'),
}
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.join(REPO, 'scripts'))
import boxpath  # noqa: E402


class SasError(RuntimeError):
    """SAS のログに ERROR が出たとき"""


def setup_console():
    """画面へ出す文字を UTF-8 にし、1行ごとに吐き出す。

    符号化。ssh 越しに呼ばれると既定では相手のコンソールのコードページ（日本語 Windows は
    cp932）で出るため、日本語のエラーが読めなくなる。RINKEN37 経由で回すときに実際に
    化けた（2026-08-22）。実コンソールへ書くときは Python が WriteConsoleW を使うので
    この指定は効かず、パイプ・ファイルへ流したときだけ効く。

    行ごとの吐き出し。Python はコンソール以外へ書くとき既定でまとめて溜める。溜めると
    30秒かかる段の途中で画面が無音になり、止まっているのか進んでいるのかが分からない。
    子プロセス（SAS・Rscript）は同じ出力先へ直接書くので、溜めたままだと親の見出しが
    子の出力より後に出て、どの段の出力かも読めなくなる。
    """
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
        except (AttributeError, ValueError):
            pass


def resolve_encoding(encoding=None):
    """符号化の指定を確定する。省略時は SAS_SESSION_ENCODING、それも無ければ utf8。"""
    if not encoding:
        encoding = os.environ.get('SAS_SESSION_ENCODING')
    if not encoding:
        encoding = 'utf8'
    encoding = encoding.lower()
    if encoding not in SAS_CONFIG:
        raise SystemExit('符号化の指定が不正です: %s（utf8 か sjis）' % encoding)
    if not os.path.isfile(SAS_CONFIG[encoding]):
        raise SystemExit('SAS の config が見つかりません: %s' % SAS_CONFIG[encoding])
    return encoding


def trial_root():
    """試験フォルダ。AKIKO_TRIAL_ROOT があればそれを使う。

    検証で出力先を本番から隔離するための口で、run-all-sas.py の --root が立てる
    （docs/records/mac-sas-r-verification-plan-20260823.md）。ログの置き場（invoke_sas の
    既定の log_dir）と wait_box_file の待ち先がここから派生するため、ここを通さないと
    ログだけ本番へ落ちる。SAS 側の autoexec.sas と R 側の ap_root() が見るのと同じ名前で、
    試験IDから組み立てる形にすると系統ごとに食い違ったときに黙って空振りする
    （2026-08-29 に一本化）。隔離していないときの探索は boxpath.py が持つ。
    """
    env = os.environ.get('AKIKO_TRIAL_ROOT')
    if env:
        if not os.path.isdir(env):
            raise SystemExit('AKIKO_TRIAL_ROOT が指す場所がありません: %s' % env)
        return os.path.abspath(env)
    return boxpath.trial_dir()


def find_rscript():
    """Rscript の在処。端末ごとの導入先は akiko-office の docs/r-environment.md が正本で、
    ここでは既定の場所と PATH の両方を見る。R は 4.6.1（renv.lock が版を固定する）。

    既定の場所が2つあるのは、導入の scope で行き先が変わるためである。利用者ごとに入れると
    %LOCALAPPDATA%\\Programs\\R、機械に入れると %ProgramFiles%\\R に置かれる。片方しか見ないと、
    もう片方で入れた端末では PATH に通っていない限り見つからない。
    """
    cands = [os.path.join(os.environ.get('LOCALAPPDATA', ''),
                          'Programs', 'R', 'R-4.6.1', 'bin', 'Rscript.exe'),
             os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'),
                          'R', 'R-4.6.1', 'bin', 'Rscript.exe')]
    for p in cands:
        if os.path.isfile(p):
            return p
    found = shutil.which('Rscript')
    if found:
        return found
    raise SystemExit('Rscript が見つかりません: %s' % ' / '.join(cands))


def log_encoding(encoding):
    """SAS はセッションの符号化でログを書く。読む側を合わせないと ERROR の検出が効かない"""
    return 'utf-8' if encoding == 'utf8' else 'cp932'


def read_log(path, encoding):
    """ログを行の一覧で読む。壊れたバイトは置換する（.NET の UTF8Encoding と同じ扱い）"""
    with open(path, encoding=log_encoding(encoding), errors='replace', newline='') as f:
        return f.read().splitlines()


def count_matches(lines, pattern):
    """行頭に錨を打った検査。PowerShell の Select-String に合わせて大小文字を区別しない"""
    rx = re.compile(pattern, re.IGNORECASE)
    return [ln for ln in lines if rx.search(ln)]


def invoke_sas(program, tag, log_dir=None, init_stmt=None, encoding=None,
               allow_error=False):
    """SAS プログラムを1本実行し、ログの ERROR を数えて報告する。

    program   … .sas の絶対パス
    tag       … ログのファイル名と画面表示に使う短い名前
    init_stmt … -initstmt へ渡す文（例 '%let lang=ja;'）。図表の言語切り替えに使う
    encoding  … utf8（既定）か sjis
    """
    enc = resolve_encoding(encoding)
    cfg = SAS_CONFIG[enc]
    if not os.path.isfile(SAS_EXE):
        raise SystemExit('SAS が見つかりません: %s' % SAS_EXE)
    if not os.path.isfile(program):
        raise SystemExit('プログラムが見つかりません: %s' % program)
    if not log_dir:
        log_dir = os.path.join(trial_root(), 'log')
    os.makedirs(log_dir, exist_ok=True)

    stamp = time.strftime('%Y%m%d')
    log = os.path.join(log_dir, '%s_%s.log' % (tag, stamp))
    lst = os.path.join(os.environ.get('TEMP', '.'), '%s.lst' % tag)

    argv = [SAS_EXE, '-config', cfg, '-sysin', program,
            '-autoexec', os.path.join(REPO, 'autoexec.sas'),
            '-sasinitialfolder', REPO, '-log', log, '-print', lst,
            '-nosplash', '-noterminal']
    if init_stmt:
        argv += ['-initstmt', init_stmt]

    t0 = time.monotonic()
    subprocess.run(argv, check=False)
    lines = read_log(log, enc)

    # Box Drive のオンデマンド取得は初回アクセスで落ちることがある。
    #   ERROR: Windows error code: 1006 in hx_disk_is_dir for ...\input\rawdata
    #   ERROR: ライブラリRAWはアクセスメソッドRANDOMには無効です。
    # libname が張れないので後続が全滅するが、一過性なので1回やり直せば通る。
    # 2026-08-22 に RINKEN37 で実測：1回目 ERROR 4・37.5秒、2回目 ERROR 0・1.3秒。
    # 311C4W991 でも初回だけ同じ 1006 が出る（akiko-office の docs/sas-environment.md）。
    if any('windows error code: 1006' in ln.lower() for ln in lines):
        print('  （%s: Box Drive の初回取得エラー 1006 を検出。1回だけやり直します）' % tag)
        subprocess.run(argv, check=False)
        lines = read_log(log, enc)

    sec = round(time.monotonic() - t0, 1)
    errs = count_matches(lines, '^ERROR')
    warns = count_matches(lines, '^WARNING')
    print('  %-22s ERROR %d  WARNING %d  %s秒  [%s]'
          % (tag, len(errs), len(warns), sec, enc))
    if errs:
        print('\n'.join(errs[:5]))
        if not allow_error:
            raise SasError('%s で ERROR が出ました（ログ %s）' % (tag, log))
    return {'tag': tag, 'error': len(errs), 'warning': len(warns),
            'seconds': sec, 'log': log}


def wait_box_file(path, timeout_sec=60):
    """Box Drive は書き込み直後に別プロセスから読むと古い版を返すことがある
    （program/r/README.md）。更新時刻とサイズが落ち着くまで待つ。
    """
    t0 = time.monotonic()
    prev = None
    while time.monotonic() - t0 < timeout_sec:
        if os.path.exists(path):
            st = os.stat(path)
            cur = '%d/%r' % (st.st_size, st.st_mtime_ns)
            if cur == prev:
                return
            prev = cur
        time.sleep(0.8)
    print('  （%s の同期待ちが %d 秒を超えました）'
          % (os.path.basename(path), timeout_sec))
