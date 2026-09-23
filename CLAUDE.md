# Kabu リポジトリについて

個人用の複数アプリをまとめたモノレポ。各アプリはディレクトリで分かれている（例: `kids-allowance/`）。

## 共有Supabaseプロジェクトについて

- 複数アプリが同じSupabaseプロジェクト **KabutoApps**（project_id: `cgwydtowirpjekmskxgx`）を共有している。
- テーブル名にアプリ名のプレフィックスを付けて同居させる運用（例: `allowance_*`, `eyetrain_*`）。
- **重要**: Supabase Authの設定（ログイン方法の有効化など）はプロジェクト単位で、同居している全アプリに影響する。新しいログイン方法を追加する前に、他アプリのRLSポリシーを確認すること。
- 現時点（2026年9月）でのRLSの状態:
  - `eyetrain_*` 系: `auth.uid()` で本人のみに制限されており安全。
  - `recipes` / `categories` / `ingredients` / `steps` / `tags` / `recipe_tags` / `source_raw` / `processing_jobs`（レシピ帳アプリ）: **`auth.role() = 'authenticated'` のみのポリシーで、ログインできる人なら誰でも読み書きできる**設計。所有者チェックがない。家族間の認証を追加した際にこの点をユーザーに確認済み・許容されている。今後さらに人を追加する場合は再度確認すること。
  - `allowance_*`（お小遣い帳）: メンバーテーブルとロール（editor/viewer）で制御。
- 別のSupabaseプロジェクト **AIStudyApp** も存在するが、上記とは別物で影響しない。

## Vercelについて

- アプリごとに個別のVercelプロジェクトを作成する運用（1プロジェクト1アプリ）。
- Hobbyプランのプロジェクト数上限には十分余裕がある。
