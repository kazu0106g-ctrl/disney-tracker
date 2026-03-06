# 🏰 Disney Wait Time Tracker — セットアップガイド

待ち時間を自動収集して Google Sheets に記録するシステムです。  
**完全無料**（GitHub Actions + Google Sheets API）

---

## 構成図

```
queue-times.com (無料API)
        ↓  15分おき
GitHub Actions (無料 cron)
        ↓
collect.py
        ↓
Google Sheets (無料)
  ├── シート「サマリー」     ← 平均待ち時間・推定入場者数
  └── シート「全アトラクション」 ← 全アトラの待ち時間ログ
```

---

## ステップ 1 — Google Cloud でサービスアカウントを作る

1. [Google Cloud Console](https://console.cloud.google.com/) を開く
2. 新規プロジェクトを作成（例: `disney-tracker`）
3. 左メニュー → **APIs & Services → ライブラリ**
4. `Google Sheets API` を検索して **有効化**
5. `Google Drive API` も検索して **有効化**
6. 左メニュー → **APIs & Services → 認証情報**
7. **「認証情報を作成」→「サービスアカウント」** を選択
8. 名前を入力（例: `disney-sheets`）→ 作成
9. 作成したサービスアカウントをクリック → **「キー」タブ**
10. **「鍵を追加」→「JSON」** → ダウンロードされる（大切に保管！）

---

## ステップ 2 — Google スプレッドシートを準備する

1. [Google スプレッドシート](https://sheets.google.com/) で新規シートを作成
2. シート名は何でもOK（例: `ディズニー待ち時間ログ`）
3. **URLからスプレッドシートIDをコピー**
   ```
   https://docs.google.com/spreadsheets/d/【ここがID】/edit
   ```
4. ダウンロードしたJSONファイルを開き、`client_email` の値をコピー
5. スプレッドシートの **共有** → そのメールアドレスを **編集者** として招待

---

## ステップ 3 — GitHub リポジトリに Secret を登録

リポジトリの **Settings → Secrets and variables → Actions → New repository secret**

| Secret名 | 値 |
|---|---|
| `SPREADSHEET_ID` | ステップ2でコピーしたID |
| `GOOGLE_CREDENTIALS` | ダウンロードしたJSONファイルの**中身をそのまま全部**貼り付け |

---

## ステップ 4 — このリポジトリを GitHub に push する

```bash
git init
git add .
git commit -m "初回コミット"
git remote add origin https://github.com/あなたのID/disney-tracker.git
git push -u origin main
```

Actions タブで **Run workflow** ボタンを押して動作確認！

---

## 実行スケジュール

| 時間帯 | 動作 |
|---|---|
| JST 9:00〜22:00 | 15分おきに自動実行 |
| それ以外 | 実行なし（パークが閉園中のため） |

GitHub Actions の無料枠は月2,000分。  
1回あたり約1〜2分 × 1日52回 × 30日 ≒ **最大3,120分**  
→ **パーク営業時間のみ実行で約1,560分で収まる** ✅

---

## スプレッドシートの見方

### 「サマリー」シート

| 列 | 内容 |
|---|---|
| 日時(JST) | 記録時刻 |
| パーク | TDL or TDS |
| 運営中アトラクション数 | その時点で動いている数 |
| 平均待ち時間(分) | 全運営中アトラクションの平均 |
| 最長待ち(分) / アトラクション名 | 一番混んでる場所 |
| 推定入場者数 | 平均待ち時間から推計 |

### 「全アトラクション」シート

全アトラクションの待ち時間を15分おきにログ保存。  
1日あたり TDL+TDS で約 60アトラ × 52回 ≒ **3,120行**追加されます。

---

## 推定入場者数の計算ロジック

TDL/TDS の最大収容約7万人を基準に、  
主要アトラクションの**平均待ち時間**から以下で推定：

| 平均待ち時間 | 推定入場者数 |
|---|---|
| 〜10分 | 〜15,000人（超空き） |
| 〜20分 | 15,000〜25,000人（空き） |
| 〜35分 | 25,000〜35,000人（普通） |
| 〜50分 | 35,000〜50,000人（やや混雑） |
| 〜70分 | 50,000〜60,000人（混雑） |
| 70分超 | 60,000〜70,000人（激混み） |

> ⚠️ あくまで推定値です。オリエンタルランドは入場者数を非公開としているため、  
> 公式の数字との照合は過去のメディア情報（例：「平日2万人」等）と比較してください。

---

## データを活用する例（Google Sheets でグラフ化）

1. サマリーシートで日時・平均待ち時間を選択
2. 挿入 → グラフ → 折れ線グラフ
3. 曜日・時間帯別の混雑パターンが見えてくる！

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| Actions が動かない | Secrets 未設定 | Settings → Secrets を確認 |
| `gspread.SpreadsheetNotFound` | 共有設定ミス | サービスアカウントのメールを編集者として招待したか確認 |
| データが来ない | パーク閉園中 | 営業時間内（JST 9:00〜22:00）に実行を確認 |
| 全行が空白 | API が `wait_time: 0` を返す | パーク閉園直後はゼロが返ることがある（正常） |

---

*Powered by [Queue-Times.com](https://queue-times.com)*  
*This is an unofficial tracker and is not affiliated with OLC or The Walt Disney Company.*
