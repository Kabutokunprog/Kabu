import SwiftUI
import CoreLocation

struct ContentView: View {
    @ObservedObject private var settings = AppSettings.shared
    @ObservedObject private var monitor = TripMonitor.shared
    @ObservedObject private var alarmer = Alarmer.shared
    @Environment(\.scenePhase) private var scenePhase
    @State private var copied = false

    var body: some View {
        NavigationStack {
            Form {
                if alarmer.isVibrating {
                    Section {
                        Button {
                            alarmer.stopCurrent()
                        } label: {
                            Label("振動を止める", systemImage: "stop.circle.fill")
                                .font(.title2.bold())
                                .frame(maxWidth: .infinity, minHeight: 60)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.orange)
                    }
                }
                statusSection
                stationSection
                permissionSection
                timeSection
                parentSection
                testSection
                Section {
                    NavigationLink("動作の記録") { LogView() }
                }
            }
            .navigationTitle("秦野アラーム")
        }
        .onAppear(perform: refresh)
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { refresh() }
        }
    }

    // MARK: - 状態

    private var statusSection: some View {
        Section {
            Toggle("見守りをする", isOn: $settings.enabled)
                .onChange(of: settings.enabled) { _, _ in monitor.ensureStandby() }
            if monitor.isTracking {
                Label {
                    if let d = monitor.distanceToDestination {
                        Text("見守り中：\(monitor.trackingName)まで \(String(format: "%.1f", d / 1000)) km")
                    } else {
                        Text("見守り中：位置を確認しています…")
                    }
                } icon: {
                    Image(systemName: "location.fill").foregroundStyle(.green)
                }
                Button("見守りを終了する", role: .destructive) { monitor.stopManually() }
            } else if monitor.isStandingBy {
                Label("待機中（省電力で位置を確認しています）", systemImage: "moon.zzz")
                    .foregroundStyle(.secondary)
            } else {
                Label("止まっています", systemImage: "pause.circle")
                    .foregroundStyle(.orange)
            }
        } footer: {
            Text("\(settings.weekdaysText)の \(AppSettings.timeText(settings.startMinutes))〜\(AppSettings.timeText(settings.endMinutes)) に\(settings.destination.startDescription)自動で見守りを始め、\(settings.destination.name)の約3分前・1分半前・50秒前に振動で知らせます（音は出ません）。")
        }
    }

    // MARK: - 降りる駅

    private var stationSection: some View {
        Section {
            Picker("降りる駅", selection: $settings.useCustomStation) {
                Text("秦野（いつもの）").tag(false)
                Text("ほかの駅").tag(true)
            }
            .pickerStyle(.segmented)
            .onChange(of: settings.useCustomStation) { _, _ in
                monitor.destinationChanged()
            }
            if settings.useCustomStation {
                NavigationLink {
                    StationPickerView()
                } label: {
                    HStack {
                        Text("駅を選ぶ")
                        Spacer()
                        Text(settings.customStation == nil ? "未設定" : "\(settings.customStationName)駅")
                            .foregroundStyle(.secondary)
                    }
                }
            }
        } header: {
            Text("降りる駅")
        } footer: {
            if settings.useCustomStation && settings.customStation == nil {
                Text("駅を選ぶまでは秦野で見守ります。")
            } else if settings.useCustomStation {
                Text("ほかの駅では、駅の8km手前に入ったら見守りを始めます。8kmより内側から乗るときは「今すぐ見守りを始める」を使ってください。")
            }
        }
    }

    // MARK: - 許可

    private var permissionSection: some View {
        Section("はじめに許可してください") {
            HStack {
                statusIcon(monitor.authorization == .authorizedAlways && monitor.preciseLocation)
                VStack(alignment: .leading) {
                    Text("位置情報：「常に」＋「正確な位置情報」")
                    Text(locationStatusText).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if monitor.authorization != .authorizedAlways || !monitor.preciseLocation {
                    Button("許可する") {
                        if monitor.authorization == .authorizedAlways {
                            monitor.openSettings()
                        } else {
                            monitor.requestPermission()
                        }
                    }
                }
            }
            HStack {
                statusIcon(alarmer.notificationsAllowed)
                Text("通知（「止める」ボタンを出すため）")
                Spacer()
                if !alarmer.notificationsAllowed {
                    Button("許可する") { monitor.openSettings() }
                }
            }
        }
    }

    private var locationStatusText: String {
        switch monitor.authorization {
        case .authorizedAlways:
            return monitor.preciseLocation ? "OK" : "「正確な位置情報」をオンにしてください"
        case .authorizedWhenInUse:
            return "「常に」に変更してください（設定アプリ → 秦野アラーム → 位置情報）"
        case .denied, .restricted:
            return "設定アプリで「常に」にしてください"
        default:
            return "まだ許可されていません"
        }
    }

    private func statusIcon(_ ok: Bool) -> some View {
        Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
            .foregroundStyle(ok ? .green : .orange)
    }

    // MARK: - 時間帯

    private var timeSection: some View {
        Section("見守る曜日と時間帯") {
            HStack(spacing: 6) {
                ForEach(1...7, id: \.self) { day in
                    let on = settings.weekdays.contains(day)
                    Button {
                        if on { settings.weekdays.remove(day) } else { settings.weekdays.insert(day) }
                    } label: {
                        Text(AppSettings.weekdayNames[day - 1])
                            .frame(maxWidth: .infinity, minHeight: 36)
                            .background(on ? Color.accentColor : Color.gray.opacity(0.2))
                            .foregroundStyle(on ? .white : .primary)
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                    .buttonStyle(.plain)
                }
            }
            DatePicker("開始", selection: minutesBinding(\.startMinutes), displayedComponents: .hourAndMinute)
            DatePicker("終了", selection: minutesBinding(\.endMinutes), displayedComponents: .hourAndMinute)
        }
    }

    private func minutesBinding(_ keyPath: ReferenceWritableKeyPath<AppSettings, Int>) -> Binding<Date> {
        Binding {
            Calendar.current.date(bySettingHour: settings[keyPath: keyPath] / 60,
                                  minute: settings[keyPath: keyPath] % 60,
                                  second: 0, of: Date()) ?? Date()
        } set: { date in
            let parts = Calendar.current.dateComponents([.hour, .minute], from: date)
            settings[keyPath: keyPath] = (parts.hour ?? 0) * 60 + (parts.minute ?? 0)
        }
    }

    // MARK: - 保護者への通知

    private var parentSection: some View {
        Section {
            HStack {
                Text("呼び名")
                TextField("娘", text: $settings.childName)
                    .multilineTextAlignment(.trailing)
            }
            Toggle("駅で降りたときも知らせる", isOn: $settings.notifyArrival)
            VStack(alignment: .leading, spacing: 4) {
                Text("トピック名（保護者の ntfy アプリに登録）")
                    .font(.caption).foregroundStyle(.secondary)
                HStack {
                    Text(settings.ntfyTopic).font(.body.monospaced()).textSelection(.enabled)
                    Spacer()
                    Button(copied ? "コピーしました" : "コピー") {
                        UIPasteboard.general.string = settings.ntfyTopic
                        copied = true
                    }
                }
            }
            Button("保護者へテスト通知を送る") { ParentNotifier.shared.sendTest() }
        } header: {
            Text("保護者への通知")
        } footer: {
            Text("保護者のスマホに無料アプリ「ntfy」を入れ、上のトピック名を登録すると、乗り過ごしたときに通知が届きます。")
        }
    }

    // MARK: - テスト

    private var testSection: some View {
        Section {
            Button("1回目の振動を試す") { Alarmer.shared.vibrate(.stage(1), station: settings.destination.name) }
            Button("2回目の振動を試す") { Alarmer.shared.vibrate(.stage(2), station: settings.destination.name) }
            Button("3回目の振動を試す") { Alarmer.shared.vibrate(.stage(3), station: settings.destination.name) }
            Button("乗り過ごしの振動を試す") { Alarmer.shared.vibrate(.overshoot, station: settings.destination.name) }
            Button("今すぐ見守りを始める（時間外でも）") { monitor.startManually() }
                .disabled(monitor.isTracking)
        } header: {
            Text("テスト")
        } footer: {
            Text("試したあと、画面を閉じても振動が続くか確認してください。20〜30秒で自動で止まります。")
        }
    }

    private func refresh() {
        // アプリを開いたときに待機を始める（画面を閉じたあとも動き続けるようにするため）
        monitor.ensureStandby()
        alarmer.requestNotificationPermission()
    }
}

struct LogView: View {
    @ObservedObject private var log = EventLog.shared

    var body: some View {
        List {
            if log.entries.isEmpty {
                Text("まだ記録はありません").foregroundStyle(.secondary)
            }
            ForEach(Array(log.entries.enumerated()), id: \.offset) { _, entry in
                Text(entry).font(.caption.monospaced())
            }
        }
        .navigationTitle("動作の記録")
        .toolbar {
            Button("消す") { log.clear() }
        }
    }
}
