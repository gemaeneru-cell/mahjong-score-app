# リアルタイム麻雀点数管理 Web アプリ（プロトタイプ）

FastAPI + python-socketio + Vanilla JavaScript で構成した、スマホ横置き前提のリアルタイム点数管理アプリです。

## 主な対応機能

- 3人 / 4人ルーム作成
- 初期持ち点設定
- 点数承認 ON / OFF
- リーチ棒（供託）管理
- ロン / ツモ入力（翻・符から自動精算）
- 3人打ちツモ損（北家分を補填しない）
- 流局開始 → 各自テンパイ / ノーテン入力 → 自動精算
- 親和了 / 親テンパイ流局で連荘・本場加算
- 箱下継続
- Undo（1手戻し）
- ホストの手動点数調整 / 原点戻し

## ルール上の前提

- 一般的なリーチ麻雀の点数表を使用
- オーラスは **親が連荘しないタイミング** で終了
- オーラス終了時に供託が残っていれば消滅
- 3人打ちツモ損は「4麻の標準支払額を、実際に存在する2人だけが払う」実装
- 本場加算は実際の支払者1人あたり +100 点
- ダブロン、パオ、責任払い、途中流局、チョンボなどは未実装

## 起動方法

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:asgi_app --reload --host 0.0.0.0 --port 8000
```

ブラウザで `http://localhost:8000` を開いてください。

## ディレクトリ構成

```text
mahjong_score_prototype/
├─ backend/
│  ├─ app/
│  │  ├─ main.py        # FastAPI / Socket.IO / ルーム管理 / 状態遷移
│  │  ├─ models.py      # ルーム・プレイヤー・承認待ち等のデータモデル
│  │  └─ scoring.py     # 翻・符計算、ロン/ツモ/流局精算ロジック
│  └─ requirements.txt
├─ frontend/
│  ├─ index.html        # 横置き前提 UI の骨組み
│  ├─ app.js            # Socket.IO 通信、状態描画、ユーザー操作
│  └─ styles.css        # スマホ横置き向けスタイル
└─ README.md
```

## 今後拡張しやすいポイント

- `scoring.py` にローカルルール分岐を追加
- `main.py` の `apply_action()` をイベントソーシング風に拡張
- 履歴を複数手に増やして多段 Undo / Redo に対応
- SQLite / Redis へ保存して再接続復元を強化
- QRコードでルーム参加リンク共有
