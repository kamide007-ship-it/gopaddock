# Go Paddock | Paddock Gait Analyzer (v2.11.4)

Go Paddock は **パドックで撮影した歩様動画** を中心に、
- **歩様の定量評価（ピッチ / ストライド / ブレ / 左右差 / 疲労兆候）**
- **血統AIの要約（傾向・得意条件）**
- **出走条件とのマッチ（距離/馬場/クラス/回り）**
- **レース内の相対評価（勝利/Top3/Top5/予想順位の確率）**

を統合してスコア化します。

> ✅ v2.11.1 では **成長予測 / 馬体生成** は一切入れず、  
> 「パドック歩様評価 + 血統 + 出走条件マッチ + 相対確率」に一本化しました。

### v2.11.4 の強化点
- `VIDEO_AI_URL` を **安全統合**（失敗してもアプリは落ちず、内蔵CVで継続）
- 血統AIを **strict JSON schema** で統一（未設定でもスキップ）
- **回り/小回り/重い馬場** など“競馬場要素”を `notes` から推定して match に反映
- レースURL入力時、対戦馬が空なら **URLから自動抽出**（失敗時は手動へ自動フォールバック）
- `VIDEO_AI_URL` は **URL-mode** に対応（アップロード動画URLだけ渡す＝安定）
- `AI_ASYNC_MODE=1` の場合は **ジョブ化(/analyze_async_url → /jobs/{id})** で待ち詰まりを回避
- MOV/HEVC は **multipart の場合のみ** 自動で MP4(H.264) へ変換（ffmpeg があれば）

---

## 必須 / 任意の環境変数（Render / ローカル共通）

### 必須（アプリ起動に必要）
- `SECRET_KEY`（または `FLASK_SECRET_KEY`）：セッション署名用（未設定でも dev 値で起動はしますが推奨）
- `DATABASE_URL`：未指定の場合 `sqlite:///app.db`

### 任意（AI連携：未設定でもアプリは落ちません）
- `OPENAI_API_KEY`：血統AI・補助コメント等（未設定ならAI部分はスキップ）
- `VIDEO_AI_URL`：外部の動画解析サービスURL（未設定なら“内蔵CV”のみで評価）
- `GPT_TEXT_MODEL`：血統要約モデル（既定はコード側）

### AI 実行の安全装置（任意・推奨）
外部動画AIが遅い/不安定でもアプリが巻き込まれないように、以下を推奨します。
- `AI_CONNECT_TIMEOUT_SECONDS`（例: 10）
- `AI_READ_TIMEOUT_SECONDS`（例: 180）
- `AI_TOTAL_TIMEOUT_SECONDS`（例: 220）
- `AI_MAX_RETRIES`（例: 3）
- `AI_RETRY_BACKOFF_SECONDS`（例: `5,20,60`）
- `AI_MAX_CONCURRENCY`（例: 1）
- `AI_ASYNC_MODE`（例: 1）… AI側が `/analyze_async_url` と `/jobs/{id}` を提供している場合

※ `VIDEO_AI_BASE_URL` も `VIDEO_AI_URL` の別名として受け付けます。

### 管理者自動作成（任意・推奨）
- `ADMIN_EMAIL`
- `ADMIN_PASSWORD`

---

## Render 起動コマンド（推奨）

```
gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120 --graceful-timeout 30
```

---

## 法的ページ（特商法/規約/プライバシー/返金）

表示URL
- `/legal/tokusho`
- `/legal/terms`
- `/legal/privacy`
- `/legal/refund`

デフォルト表記（環境変数で上書き可）
- 販売事業者名：`SELLER_NAME`（既定: Equine Vet Synapse）
- お問い合わせ：`CONTACT_EMAIL`（既定: equinevet.owners@gmail.com）
- 会社サイト：`BUSINESS_SITE`（既定: https://www.minamisoma-vet.com/）
- 所在地：`ADDRESS`（未設定の場合は空欄）

---

## 仕様メモ
- 本リポジトリは **「パドック歩様」専用** です（成長予測・馬体生成は含みません）。
- AIや外部動画AIが落ちても、アプリ全体が落ちない（best-effort）設計です。

### MOV/HEVC（iPhone動画）対策
Render 上の OpenCV は MOV(HEVC/H.265) をデコードできず、解析が詰まって 504 になりやすいことがあります。
このため、アップロードされた動画が `.mov` の場合は **サーバ側で H.264/AAC のMP4へ自動変換**してから解析へ渡します。

- 変換は `imageio-ffmpeg` 同梱の ffmpeg バイナリを使うため、apt-get は不要です。
- 変換に失敗した場合は、アプリは落ちずに「動画AI部分のみスキップ or 元動画のままbest-effort」で続行します。

環境変数:
- `VIDEO_TRANSCODE_ENABLED` : `1`/`0`（デフォルト `1`）
