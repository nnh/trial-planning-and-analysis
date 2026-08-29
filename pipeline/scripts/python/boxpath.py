# boxpath.py
#
# Box 上の試験フォルダの場所を1か所で決める。Windows（SAS 実行機）と macOS の両方で
# 同じスクリプトが動くようにするための小さな共通部品。
#
# 解決の順序
#   1. 環境変数 AKIKO_BOX_ROOT（明示指定。他の場所に置いた複製を見るときに使う）
#   2. macOS の Box Drive        ~/Library/CloudStorage/Box-Box
#   3. 旧 Box Drive・手動同期     ~/Box
#   4. Windows の Box Drive      %USERPROFILE%\Box
#
# Box が無い端末でも import は失敗させない。呼ぶ側が trial_dir(required=False) で
# None を受け取り、Box を要る処理だけを飛ばせるようにしてある。
import json
import os

# 試験固有の値は docs/metadata/trial.json だけが持つ。ここを差し替えれば同じスクリプトが
# 別の試験で動く。boxpath を import する側は trial_id() と trial_dir() だけを使い、
# 試験名をコードに書かない。
CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'docs', 'metadata', 'trial.json')


def config():
    """docs/metadata/trial.json を読む。無ければ何が足りないかを言って止まる。"""
    try:
        with open(CONFIG, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        raise SystemExit('\n'.join([
            f'試験の設定が無い: {CONFIG}',
            '次の形で作る:',
            '  {"trial_id": "<試験ID>", "box_path": ["Stat", "Trials", "<グループ>", "<試験ID>"]}',
        ]))


def trial_id():
    """プログラム名・パッケージ名・表題に使う試験の識別子"""
    return config()['trial_id']


TRIAL = os.path.join(*config()['box_path'])


def candidates():
    home = os.path.expanduser('~')
    out = []
    env = os.environ.get('AKIKO_BOX_ROOT')
    if env:
        out.append(env)
    out.append(os.path.join(home, 'Library', 'CloudStorage', 'Box-Box'))
    out.append(os.path.join(home, 'Box'))
    up = os.environ.get('USERPROFILE')
    if up:
        out.append(os.path.join(up, 'Box'))
    return out


def box_root():
    """Box のルート。見つからなければ None"""
    for p in candidates():
        if os.path.isdir(p):
            return p
    return None


def trial_dir(required=True):
    """試験のフォルダ。required=False なら無いとき None を返す"""
    root = box_root()
    if root:
        p = os.path.join(root, TRIAL)
        if os.path.isdir(p):
            return p
    if not required:
        return None
    raise SystemExit(
        'Box の試験フォルダが見つからない。Box Drive を入れるか、AKIKO_BOX_ROOT で場所を指定する。\n'
        '探した場所:\n  ' + '\n  '.join(candidates()))
