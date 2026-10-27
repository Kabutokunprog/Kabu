# 引き継ぎメモ：見守りが途中で止まる問題の修正（2026-10-27）

Mac 側の Claude Code へ。この版を Mac の作業フォルダに反映し、TestFlight に上げるところまでお願いします。
利用者はプログラミングに詳しくないので、敬語で、平易な言葉で説明してください。

---

## 1. 起きていた問題

実機（娘さんの iPhone）の「動作の記録」画面より：

```
10/26 15:54:16  伊勢原駅付近に入りました（時間外なので何もしません）
10/26 16:06:48  秦野までの見守りを開始しました（鶴巻温泉駅付近に入ったため）
（ここから何も記録なし）
10/27 00:57:48  1時間たったので見守りを終了しました
10/27 00:57:48  GPS を止めました
10/27 07:03:30  鶴巻温泉駅付近に入りました（時間外なので何もしません）
10/27 07:11:37  伊勢原駅付近に入りました（時間外なので何もしません）
10/27 19:23:55  秦野までの見守りを開始しました（伊勢原駅付近に入ったため）
（ここから何も記録なし。振動も「降りた」判定もなし）
10/27 21:02:22  1回目のバイブを始めました   ← 手動の振動テスト（振動自体は OK）
```

- ジオフェンス（伊勢原・鶴巻温泉への進入）は毎回正しく検知できている。朝の東京方面（鶴巻温泉→伊勢原の順）も正しく無視できている。
- しかし見守り開始の**直後にアプリが眠らされている（サスペンド）**。
  - 16:06 開始の見守りは本来 17:06 にタイムアウトするはずが、記録は 0:57。その間アプリが一度も動いていない（5 秒ごとのタイマーも位置更新も来ていない）。
  - 19:23 開始の見守りでは、振動・到着・タイムアウトのどれも記録されていない。

## 2. 原因

`CLLocationManager.allowsBackgroundLocationUpdates` の Apple 公式説明より：

> When the value of this property is true and you start location updates **while the app is in the foreground**, Core Location configures the system to keep the app running to receive continuous background location updates.

旧版は、**ジオフェンスでアプリが裏で起こされた瞬間（バックグラウンド）に** `startUpdatingLocation()` と `CLBackgroundActivitySession()` を始めていた。
バックグラウンドで始めた位置更新では、iOS はアプリを起こし続けてくれない。そのため、起こされてから約10秒でまたサスペンドされていた。
（`CLBackgroundActivitySession` も「前面で作り、アプリが終了させられたら、裏で起動された直後に作り直す」のが Apple の想定する使い方。）

## 3. 修正内容（コミット f933aa9）

### 3-1. 待機モード（主な対策）— `TripMonitor.swift`
- 新しく `ensureStandby()` を追加。**アプリを開いたとき（前面）**に、省電力の位置更新を始めておく。設定は次のとおり。
  - `desiredAccuracy = kCLLocationAccuracyKilometer`、`distanceFilter = 500`（電波・Wi-Fi 中心で、GPS はほぼ使わない）
  - `allowsBackgroundLocationUpdates = true`、`CLBackgroundActivitySession` を作成
  - `showsBackgroundLocationIndicator = false`（待機中）
- これでアプリがサスペンドされず、常に裏で動き続ける。
- 見守り開始時（`startTrip`）は精度を `kCLLocationAccuracyBest` ／ `kCLDistanceFilterNone` に上げるだけ。見守り終了時（`finishTrip`）は GPS を止めずに**待機の精度に戻す**。
- `ensureStandby()` を呼ぶ場所は次の4つ。
  - `setup()`（`AppDelegate` の起動時。裏での起動時も Apple の決まりどおり即座に作り直すため）
  - 位置情報の許可が変わったとき
  - 画面が前面に来たとき（`ContentView.refresh()`）
  - 「見守りをする」トグルを変えたとき
- 「見守りをする」がオフ、または「常に」許可がない場合は、`stopEverything()` で位置更新を完全に止める。
- 待機中の大まかな位置（精度 1500m 以内）でも、見張りエリア（伊勢原 1.5km・鶴巻温泉 1.2km、ほかの駅は 8km）に「入った瞬間」を検知して見守りを始める（`checkWatchAreaEntry`）。ジオフェンスの知らせが遅れたときの保険。

### 3-2. 予備のジオフェンス — `Destination.swift`、`TripMonitor.swift`、`TripLogic.swift`
- `Destination.stageAreas` を追加。降りる駅を中心に、半径 3.5km・2km の円もジオフェンス登録する（秦野なら全部で4つ）。
- このどちらかに入ったときに、伊勢原・鶴巻温泉で見守りを始めてから40分以内（`armedAt` を UserDefaults に保存）で、かつ時間帯内なら、次のように動く。
  - 見守りが無ければ開始する（アプリが終了させられていた場合の復旧）
  - `TripLogic.markStageDue(n)` で n 回目までを鳴らす対象にし、振動させる
- 40分の条件は、地元（秦野駅の近く）を移動しただけで鳴らないようにするため。見守りを終えると `armedAt` は消す。

### 3-3. 振動中にサスペンドされない — `Alarmer.swift`
- 振動を始めるときに `UIApplication.beginBackgroundTask` を取り、止めるときに終える。ジオフェンスで起こされた直後でも、20〜30秒の振動を最後まで出せるようにするため。

### 3-4. 画面 — `ContentView.swift`
- 状態の表示を3つにした：「見守り中」／「待機中（省電力で位置を確認しています）」／「止まっています」。

### 3-5. テスト — `Tests/main.swift`
- 7番目のパターン「GPS が届かず、予備の知らせだけが来た」を追加。全7パターン OK。
  実行方法：`swiftc HadanoAlarm/TripLogic.swift Tests/main.swift -o /tmp/t && /tmp/t`
- GitHub Actions（Xcode 16.4）でのシミュレータ向けビルドも成功を確認済み。

## 4. Mac 側でやってほしいこと

1. **ファイルの反映**
   - 新しい版の置き場所：利用者に「ダウンロード」フォルダへ保存してもらった `~/Downloads/HadanoAlarm.zip`。
     無い場合は GitHub の `Kabutokunprog/Kabu` リポジトリ、ブランチ `claude/hadano-alarm` の `HadanoAlarm` フォルダ（中身は同じ）。
   - 作業フォルダ：`/Users/juntakeda/Documents/JT/☆KabutoSolutions起業/ClaudeFolder/HadanoAlarm`
   - **上書きしてはいけないもの**：`HadanoAlarm.xcodeproj/project.pbxproj` にある、利用者が Xcode で設定した `DEVELOPMENT_TEAM`、`PRODUCT_BUNDLE_IDENTIFIER`、`CURRENT_PROJECT_VERSION`、`MARKETING_VERSION`。
     新しい版の pbxproj は `DEVELOPMENT_TEAM = ""`、ビルド番号 1 のまま。**このファイルは丸ごと置き換えず、今の作業フォルダのものを残す**のが安全（今回の修正では pbxproj は変わっていない）。
   - 置き換えるのは `HadanoAlarm/*.swift`、`Tests/main.swift`、`README.md`、`HANDOFF.md`。今回の修正で変わったのは次の6ファイル。
     - `HadanoAlarm/TripMonitor.swift`
     - `HadanoAlarm/Alarmer.swift`
     - `HadanoAlarm/ContentView.swift`
     - `HadanoAlarm/Destination.swift`
     - `HadanoAlarm/TripLogic.swift`
     - `Tests/main.swift`
   - 作業フォルダは iCloud 上にある。ファイルがクラウドにだけあってビルドで見つからない場合は、Finder で「今すぐダウンロード」してもらう。
2. **テストとビルドの確認**：上のテストコマンドを実行し、そのあと Xcode（または `xcodebuild`）でビルドが通ることを確認する。
3. **ビルド番号を上げる**：`CURRENT_PROJECT_VERSION` を、前回 TestFlight に上げた番号より 1 大きくする（わからなければ利用者に確認）。
4. **Archive → TestFlight へアップロード**：Xcode の Product → Archive → Distribute App → TestFlight & App Store。
   または `xcodebuild archive` と `-exportArchive`（`-allowProvisioningUpdates` 付き、destination を upload にした ExportOptions）。
5. **アップデート後の確認**（利用者にお願いする）
   - 娘さんの iPhone で TestFlight から更新し、**一度アプリを開く**。画面上部に「待機中（省電力で位置を確認しています）」と出れば OK。
   - iPhone を再起動したあとや、アプリを更新したあとも、一度アプリを開く必要がある。
   - 次の帰り道のあと「動作の記録」を確認する。期待する並び：
     「待機を始めました」→「秦野までの見守りを開始しました」→「1回目／2回目／3回目のバイブを始めました」→「秦野駅で降りたと判断しました」→「見守りを終えて、待機に戻りました」

## 5. 気にしておくこと（未確認の点）

- **電池**：待機中も大まかな位置を確認し続けるため、旧版よりは電池を使う。数日後に「設定 → バッテリー」で使用率を見てもらい、多ければ `distanceFilter` を広げるなどで調整する。
- **アプリの強制終了**：上にスワイプして終了すると、待機も止まる。その場合は予備のジオフェンス（3.5km圏・2km圏）だけが頼りになり、3回目（800m）は鳴らない可能性がある。
- 待機を始めたあと、画面を閉じても本当に起こされ続けるかは、まだ実機で確認していない。記録に「見守りを開始しました」の後の振動が出るかで確かめる。
