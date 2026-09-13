# run-release.py
#
# 固定データから納品までを一続きで回し、どこかで検査が落ちたらそこで止める。
#
# なぜ要るか。2026-08-29 まで、SAS 系を回す run-all-sas だけが一括の入口で、R 系の
# 生成・層ごとの突合・ARS の検証・成果物の検査は手で回していた。二重コーディングで
# 不一致0という事実は、その時点で人が回した記録にとどまり、現行のコードに対する条件では
# なかった（docs/validation/records/codex-review-2-ledger.md の C2-009・C2-198・C2-097）。
#
# 段階は次のとおり。前の段階が落ちたら後ろは回さない。
#   1. SAS 系の生成（run-all-sas.py。中で QC のゲートが働く）
#   2. R 系の生成（SDTM → ADaM → ARD → 図表）
#   3. ADaM の define（宣言と実データの照合・define.xml・define.html）
#   4. トレーサビリティ索引（仕様書 HTML → 作業用の索引 → ブラウザでの確認）
#   5. 層ごとの突合（SDTM・ADaM・ARD と主要評価項目の判定・図表のセル台帳）
#   6. ARS の生成・スキーマ検証・両系統の突合・成果物との照合
#   7. 成果物の検査（宣言と題名・視覚回帰）
#
# 段階3を段階2の直後に置くのは、ADaM の define.xml が読むもののうち回ごとに変わる唯一の
# 材料が ADaM の Dataset-JSON（段階2の出力）だからである。残りの材料（variable-map.csv・
# adam-codelist.csv・ADaM IG の写し）は git が持つので回では変わらない。依存が確定するのが
# 段階2の終わりなので、その次に置く。後ろへ回すと、define を作らないまま突合と検査だけが
# 通る段階が生まれる。2026-09-05 まで ADaM の define はこの通し実行の外にあり、ADSL の
# 変数の由来を変えても追随せず、古いものが納品パッケージへ入りかけた。
#
# 段階4をその次に置くのは、索引が埋める解析値と張るリンクのうち、回ごとに変わる材料が
# 段階2の出力（R 系の ARD・Dataset-JSON・図表 HTML）と段階3の出力（ADaM の define.xml）だけで、
# それがすべて確定するのが段階3の終わりだからである（変数マップ・帳票の一覧・表示文言は git が持つ）。
# 2026-09-05 まで作業用の索引はこの通し実行の外にあり、手で build-traceability.py を回したときだけ
# 作り直していたため、同じ名前の索引が納品パッケージの中と作業用の二箇所にあって、作業用だけが古い状態に
# なっていた。仕様書 HTML を先に回すのは、索引がその節の id を読んで実在する節だけへリンクを出すためである。
#
# SDTM の define と CDISC CORE は run-sdtm-validation.py が持ち、ここには入れていない。
#
# 使い方
#   python scripts/run-release.py              ... 全段階
#   python scripts/run-release.py --from 3     ... 3段階目から（前の生成物を使う）
#   python scripts/run-release.py --skip-sas   ... SAS 系の生成を飛ばす
#
# --from と --skip-sas は前の回の生成物を使うので、その回が今のコードと同じ版で、成果物が
# その後書き換わっていないことを先に確かめる。確かめずに使うと、別々の回に作った層を
# 混ぜたまま突合が「不一致0」で通る（C3-127）。段階ごとの記録は Box の
# output/qc/release-manifest.json に置く（成果物と同じで git 管理外）。
#
# 確かめるのはコミットと成果物のハッシュだけではない。受領データ直下の指紋、宣言
# （docs/metadata・docs/validation/acceptance の CSV）の指紋、環境の版も記録し、前の回と
# 違えば再利用させない。コミットが同じままでも受領データは差し替わり（再抽出）、宣言は
# 直され、処理系は入れ替わる。どれも成果物の意味を変えるが、コミットには現れない。
# また、ある段階を回し直したら、それより後の段階の成功記録は捨てる。残すと、途中で
# 落ちた回でも以前の後続段階が「同じ回に通った」ものとして再利用される。
#
# 段ごとの成果物のうち、枠組みが名前を知っているのは段階1・2・3・4・6 である。突合と
# 視覚回帰の出力は試験側のプログラムが決めるので名指しできない。試験側が
# docs/metadata/release-artifacts.csv に宣言する。宣言の無い段を飛ばそうとすると、
# 実施した記録だけでは同じ回のものだと確かめられないので落とす。
#
# 終了コード 0 全段階が通った / 1 どこかで落ちた
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boxpath  # noqa: E402
import runcommon  # noqa: E402

REPO = runcommon.REPO
SCRIPTS = os.path.join(REPO, 'scripts')
PY = sys.executable


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S')


# ---------------------------------------------------------------------------------
# 段階ごとの記録。どの版のコードで、どの成果物を作った回かを残す。--from・--skip-sas で
# 前の回の生成物を使うときに、それが今の版と同じ回のものかを確かめるために要る（C3-127）
# ---------------------------------------------------------------------------------
# 段階が作る成果物のうち、後ろの段階が材料として読むもの。ここが前の回と入れ替わって
# いると、層をまたぐ突合が別々の回の材料を比べることになる。段階3以降は後続が読む
# 材料を作らないので、記録するのは実施したことだけにする
# パスは要素で持つ。区切りを文字列に書くと、書いた側の処理系でしか解決しない
# （macOS ではバックスラッシュがファイル名の一部になり、成果物を見つけられない）。
# 記録の鍵は / で綴り、読むときに区切りを揃える。
STEP_ARTIFACTS = {
    1: [('datasets', 'sas', 'ard', 'ard_cards.csv'),
        ('output', 'compare', 'tlf_cells_sas_ja.csv'),
        ('output', 'compare', 'tlf_cells_sas_en.csv')],
    2: [('datasets', 'r', 'ard', 'ard_cards_r.csv'),
        ('output', 'compare', 'tlf_cells_r_ja.csv'),
        ('output', 'compare', 'tlf_cells_r_en.csv'),
        ('output', 'compare', 'tlf_cells_rsas_ja.csv'),
        ('output', 'compare', 'tlf_cells_rsas_en.csv')],
    3: [('datasets', 'define', 'adam', 'define.xml')],
    4: [('output', 'tlf', 'traceability.html')],
    6: [('datasets', 'sas', 'ard', 'reporting-event-sas.json'),
        ('datasets', 'r', 'ard', 'reporting-event-r.json')],
}

# 枠組みが名前を知らない成果物は試験側が宣言する。突合と視覚回帰の出力は試験側の
# プログラムが決めるので、ここで名指しできない。宣言が無い段は、実施の記録だけで
# 再利用されることになるため、飛ばす対象になったときに落とす。
DECLARED_ARTIFACTS = ('docs', 'metadata', 'release-artifacts.csv')

# 宣言の指紋に入れる置き場。回ごとに変わらないが、版が変われば成果物の意味が変わる
DECL_DIRS = (('docs', 'metadata'), ('docs', 'validation', 'acceptance'))

# 受領データの置き場。解析が読むのは直下だけ（data-verification.md 4.9）
INPUT_PARTS = ('input', 'rawdata')


def rel_key(parts):
    """記録の鍵。処理系によらず / で綴る。"""
    return '/'.join(parts)


def norm_key(key):
    """記録から読んだ鍵の区切りを揃える。旧い記録は \\ で綴られている。"""
    return key.replace(chr(92), '/')


def declared_artifacts(repo):
    """試験側が宣言した段ごとの成果物。無ければ空。"""
    p = os.path.join(repo, *DECLARED_ARTIFACTS)
    out = {}
    if not os.path.isfile(p):
        return out
    import csv
    with open(p, encoding='utf-8-sig', newline='') as f:
        rdr = csv.DictReader(f)
        if not rdr.fieldnames or 'step' not in rdr.fieldnames or 'path' not in rdr.fieldnames:
            return out
        for r in rdr:
            s = (r.get('step') or '').strip()
            path = (r.get('path') or '').strip().replace(chr(92), '/')
            if s.isdigit() and path:
                out.setdefault(int(s), []).append(tuple(path.split('/')))
    return out


def decl_digest(repo):
    """宣言の指紋。宣言が変われば、同じコミットでも成果物の意味が変わる。"""
    h = hashlib.sha256()
    for parts in DECL_DIRS:
        d = os.path.join(repo, *parts)
        if not os.path.isdir(d):
            continue
        for n in sorted(os.listdir(d)):
            f = os.path.join(d, n)
            if os.path.isfile(f) and n.lower().endswith('.csv'):
                h.update(n.encode('utf-8'))
                h.update(sha256(f).encode('ascii'))
    return h.hexdigest()


def env_id():
    """環境の版。処理系が変われば数値の再現は別の話になる。"""
    import platform
    return '%s %s / %s %s' % (platform.python_implementation(),
                              platform.python_version(),
                              platform.system(), platform.machine())


def input_digest(box):
    """受領データ直下の指紋。名前とハッシュを並べて1つにまとめる。

    これを持たないと、同じコミットのまま受領データを差し替えても、記録した成果物さえ
    据え置けば再開の検査が通る。層の材料が入れ替わったことに気づけない。
    """
    d = os.path.join(box, *INPUT_PARTS)
    if not os.path.isdir(d):
        return ''
    h = hashlib.sha256()
    for n in sorted(os.listdir(d)):
        f = os.path.join(d, n)
        if os.path.isfile(f):
            h.update(n.encode('utf-8'))
            h.update(sha256(f).encode('ascii'))
    return h.hexdigest()


class Release:
    def __init__(self, box, commit, dirty, repo=None, run_id=None):
        self.box = box
        self.commit = commit
        self.dirty = dirty
        self.repo = repo or REPO
        # 実行IDは1回の通しを通して同じ。段ごとの記録が同じ回のものかを、時刻でなく
        # この値で見る。時刻は近ければ同じ回に見えるが、近いことは同じ回の証拠にならない
        self.run_id = run_id or time.strftime('%Y%m%dT%H%M%S')
        self.manifest = os.path.join(box, 'output', 'qc', 'release-manifest.json')

    def artifacts_for(self, no):
        return list(STEP_ARTIFACTS.get(no, [])) + list(
            declared_artifacts(self.repo).get(no, []))

    def load(self):
        if not os.path.isfile(self.manifest):
            return None
        try:
            with open(self.manifest, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def save_step(self, no):
        m = self.load()
        steps = {}
        # 別の版で作った段階の記録は引き継がない。引き継ぐと、版をまたいで積み上げた記録が
        # 再開の検査を通してしまう
        if m and m.get('commit') == self.commit and m.get('steps'):
            steps.update(m['steps'])
        # 上流を回し直したら、下流の成功記録は無効にする。残すと、途中で落ちた回でも
        # 以前の後続段階が「同じ回に通った」ものとして再利用される
        for later in [k for k in steps if k.isdigit() and int(k) > no]:
            del steps[later]
        h = {}
        for parts in self.artifacts_for(no):
            f = os.path.join(self.box, *parts)
            h[rel_key(parts)] = sha256(f) if os.path.isfile(f) else ''
        steps[str(no)] = {'at': now(), 'run': self.run_id, 'artifacts': h}
        obj = {'commit': self.commit, 'dirty': self.dirty, 'at': now(),
               'run': self.run_id,
               'input': input_digest(self.box),
               'declarations': decl_digest(self.repo),
               'env': env_id(),
               'steps': steps}
        os.makedirs(os.path.dirname(self.manifest), exist_ok=True)
        text = json.dumps(obj, ensure_ascii=False, indent=2)
        with open(self.manifest, 'w', encoding='utf-8', newline='\r\n') as f:
            f.write(text + '\n')

    def check_reuse(self, step_nos):
        """飛ばす段階の材料が、今の版で作られてその後変わっていないことを確かめる。
        確かめられなければ何が足りないかを述べて落とす（黙って前の回の材料を使わない）"""
        bad = []
        m = self.load()
        if not m:
            bad.append('前の回の記録が無い（%s）。一度は通しで回す' % self.manifest)
            return bad
        if m.get('commit') != self.commit:
            bad.append('前の回はコミット %s、今は %s' % (m.get('commit'), self.commit))
        if m.get('dirty') or self.dirty:
            bad.append('作業ツリーに未コミットの変更がある。どの版で作った成果物かを確かめられない')
        now_input = input_digest(self.box)
        if not m.get('input'):
            bad.append('前の回の記録に受領データの指紋が無い。通しで回して記録を作り直す')
        elif m.get('input') != now_input:
            bad.append('受領データが前の回から変わっている。段を飛ばすと、別のカットで'
                       '作った層が混ざる')
        if not m.get('declarations'):
            bad.append('前の回の記録に宣言の指紋が無い。通しで回して記録を作り直す')
        elif m.get('declarations') != decl_digest(self.repo):
            bad.append('宣言（docs/metadata・docs/validation/acceptance の CSV）が'
                       '前の回から変わっている。同じコミットでも成果物の意味が変わる')
        if m.get('env') and m.get('env') != env_id():
            bad.append('環境が前の回と違う（前 %s / 今 %s）' % (m.get('env'), env_id()))
        for n in step_nos:
            s = (m.get('steps') or {}).get(str(n))
            if not s:
                bad.append('[%d] を実施した記録が無い' % n)
                continue
            if not (s.get('artifacts') or {}):
                bad.append('[%d] は成果物の記録を持たない。実施した記録だけでは、'
                           '同じ回のものだと確かめられない。'
                           'docs/metadata/release-artifacts.csv にこの段の'
                           '成果物を宣言する' % n)
                continue
            for key, want in (s.get('artifacts') or {}).items():
                rel = norm_key(key)
                f = os.path.join(self.box, *rel.split('/'))
                if not want:
                    bad.append('[%d] %s は前の回に作られていない' % (n, rel))
                    continue
                if not os.path.isfile(f):
                    bad.append('[%d] %s が無い' % (n, rel))
                    continue
                if sha256(f) != want:
                    bad.append('[%d] %s が前の回から変わっている' % (n, rel))
        return bad


def run(argv, cwd=None):
    """外部プロセスを1本回して終了コードを返す。出力は画面へそのまま流す"""
    return subprocess.run(argv, cwd=cwd or REPO, check=False).returncode


def main():
    runcommon.setup_console()
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='from_step', type=int, default=1)
    ap.add_argument('--skip-sas', action='store_true')
    ap.add_argument('--encoding', choices=['utf8', 'sjis'], default='utf8')
    args = ap.parse_args()

    os.chdir(REPO)
    rscript = runcommon.find_rscript()
    # 試験フォルダの場所は boxpath.py が持つ（端末ごとに Box の同期先が違う）
    box = boxpath.trial_dir()
    # 試験 ID は docs/metadata/trial.json だけが持つ。R プログラム名の組み立てに使う
    trial = boxpath.trial_id()

    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO, check=True,
                            capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(['git', 'status', '--porcelain'], cwd=REPO, check=True,
                                capture_output=True, text=True).stdout.strip())
    rel = Release(box, commit, dirty)

    def r(*a):
        return run([rscript] + list(a))

    def py(script, *a):
        return run([PY, os.path.join(SCRIPTS, script)] + list(a))

    def rprog(name, *a):
        """program/r 配下の R プログラム。名前は <試験ID>_<段階>.R で組み立てる"""
        return r(os.path.join(REPO, 'program', 'r', '%s_%s.R' % (trial, name)), *a)

    def step1():
        if args.skip_sas:
            print('  --skip-sas のため飛ばす')
            return 0
        return py('run-all-sas.py', '--encoding', args.encoding)

    def step2():
        for f in ('CSVtoSDTM', 'SDTMtoADaM', 'ARD'):
            code = rprog(f)
            if code:
                return code
        # 図表は両方の ARD から描く。r-* が納品、rsas-* は描画だけを比べるための材料
        code = rprog('TLF', '--lang=both', '--ard=r')
        if code:
            return code
        return rprog('TLF', '--lang=both', '--ard=sas')

    def step3():
        # 宣言と実データの照合 → define.xml → define.html。順序と中身は
        # run-adam-validation.py が正本で、ここへ写さない
        return py('run-adam-validation.py')

    def step4():
        # 仕様書 HTML → 索引 → ブラウザでの確認の順。作業用の索引の出力先は
        # build-traceability.py の既定（output/tlf/traceability.html）に任せ、ここでは名指しない。
        # 仕様書側の戻り道だけは作業用の並び（output/spec から見た索引）を渡す。
        # 既定はパッケージの並び（16_1_9_methods から直下）で、作業用では解決しない
        code = py('build-spec-html.py', '--back', '../tlf/traceability.html')
        if code:
            return code
        code = py('build-traceability.py')
        if code:
            return code
        return py('check-traceability.py')

    def step5():
        for f in ('CompareSDTM', 'CompareADaM', 'Compare'):
            code = rprog(f)
            if code:
                return code
        # 図表のセルは4通り突き合わせる。描画系統の突合（SAS の描画 対 R の描画）を日英で、
        # 数値の系統の突合（同じ R の描画で ARD だけ入れ替える）を日英で。既定の1通りだけだと
        # 英語版しか見ておらず、日本語版だけで起きる食い違い（表示名で並べ替えていたための
        # 行の入れ替わり。C2-213）を取り逃がす（2026-08-31）
        cmp_r = os.path.join(REPO, 'program', 'r', '%s_CompareTLF.R' % trial)
        pairs = [('tlf_cells_sas_ja.csv', 'tlf_cells_rsas_ja.csv'),
                 ('tlf_cells_sas_en.csv', 'tlf_cells_rsas_en.csv'),
                 ('tlf_cells_rsas_ja.csv', 'tlf_cells_r_ja.csv'),
                 ('tlf_cells_rsas_en.csv', 'tlf_cells_r_en.csv')]
        # 台帳が片方でも無い組を飛ばすと、系統・言語の生成失敗も出力先の誤りも見逃したまま
        # この段階が通る（C3-122）。比較を始める前に4組8ファイルがそろっているかを見て、1本でも
        # 無ければ何が無いかを述べて落とす。飛ばした比較を成功として数えない
        need = sorted({n for pair in pairs for n in pair})
        miss = [n for n in need
                if not os.path.isfile(os.path.join(box, 'output', 'compare', n))]
        if miss:
            print('  突合に要る台帳が無い: %s' % '、'.join(miss))
            print('  図表の生成が落ちているか、出力先か名前が違う。図表の突合を1件も実施していない。')
            return 1
        for a, b in pairs:
            code = r(cmp_r, '--a=%s' % os.path.join(box, 'output', 'compare', a),
                     '--b=%s' % os.path.join(box, 'output', 'compare', b))
            if code:
                return code
        # 上の4通りはいずれも同一言語の中の比較なので、両描画系統が共有する言語固有の行欠落・
        # 入替えは通ってしまう（C3-121）。同じ描画・同じ ARD の日本語版と英語版を、行数・
        # 列構造・由来鍵・行キーの対応で突き合わせる。表示値は言語で変わるので比べない。
        # 3組は描画と ARD の組合せ（SAS描画×SAS ARD、R描画×SAS ARD、R描画×R ARD）
        for s in ('sas', 'rsas', 'r'):
            code = r(cmp_r,
                     '--a=%s' % os.path.join(box, 'output', 'compare',
                                             'tlf_cells_%s_ja.csv' % s),
                     '--b=%s' % os.path.join(box, 'output', 'compare',
                                             'tlf_cells_%s_en.csv' % s),
                     '--mode=lang')
            if code:
                return code
        return 0

    def step6():
        for sysname in ('sas', 'r'):
            code = py('build-ars-json.py', '--system', sysname)
            if code:
                return code
        for script in ('check-ars-json.py', 'compare-ars-json.py'):
            code = py(script)
            if code:
                return code
        return py('check-ars-tlf.py', '--system', 'r')

    def step7():
        code = py('check-tlf-index.py')
        if code:
            return code
        # 引数を渡さないと納品する4組（r・sas × ja・en）を見る。--allow-skip は渡さない。
        # playwright や Box が無い端末で 0 が返ると、1件も撮らないままこの段階が通る（C3-124）
        return py('check-visual-regression.py')

    plan = [(1, 'SAS 系の生成', step1), (2, 'R 系の生成', step2),
            (3, 'ADaM の define', step3), (4, 'トレーサビリティ索引', step4),
            (5, '層ごとの突合', step5), (6, 'ARS の生成と検証', step6),
            (7, '成果物の検査', step7)]

    # 前の回の生成物を使う段階を先に検査する。1件でも確かめられなければ何も回さずに落とす
    reuse = [n for n in range(1, len(plan) + 1) if n < args.from_step]
    if args.skip_sas and 1 not in reuse:
        reuse = [1] + reuse
    if reuse:
        bad = rel.check_reuse(reuse)
        if bad:
            print('前の回の生成物を使えません:')
            for b in bad:
                print('  %s' % b)
            print('飛ばす段階（%s）の材料が同じ回のものだと確かめられないので、通しで回すこと。'
                  % '、'.join(str(n) for n in reuse))
            return 1
        print('前の回（コミット %s）の生成物を使う: 段階 %s'
              % (commit, '、'.join(str(n) for n in reuse)))

    for no, name, body in plan:
        if no < args.from_step:
            print('[%d] %s … 飛ばす（--from %d）' % (no, name, args.from_step))
            continue
        print('')
        print('=== [%d] %s ===' % (no, name))
        t = time.monotonic()
        code = body()
        sec = round(time.monotonic() - t, 1)
        if code != 0:
            print('')
            print('落ちた段階: [%d] %s（終了コード %d）' % (no, name, code))
            print('[%d] %s で落ちました。直してから通すこと。' % (no, name))
            return 1
        rel.save_step(no)
        print('  通った（%s 秒）' % sec)

    print('')
    print('全段階が通りました。納品パッケージは scripts/build-pi-package.py で作ります。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
