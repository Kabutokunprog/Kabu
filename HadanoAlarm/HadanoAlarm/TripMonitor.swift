import Foundation
import CoreLocation
import UIKit

/// 位置情報の見張り役。
///
/// iPhone は、画面を閉じたアプリをすぐ眠らせる。GPS を「アプリを開いているときに」始めておくと
/// 眠らせずにおいてくれるが、眠っている最中に GPS を始めても、すぐまた眠らされてしまう。
/// そこで次の二段構えにする。
/// 1. 待機：アプリを開いたときに、省電力（電波・Wi-Fi で大まかに）の位置確認を始めておく。
///    これでアプリが眠らされず、時間帯に伊勢原付近へ入ったら GPS を細かくする。
/// 2. 予備：iPhone の「場所の見張り（ジオフェンス）」で伊勢原・鶴巻温泉と、秦野の 3.5km 圏・2km 圏を見張る。
///    万一アプリが止まっていても、ここに入ればアプリが起こされ、振動させられる。
final class TripMonitor: NSObject, ObservableObject, CLLocationManagerDelegate {
    static let shared = TripMonitor()

    @Published private(set) var authorization: CLAuthorizationStatus = .notDetermined
    @Published private(set) var preciseLocation = true
    @Published private(set) var isTracking = false
    @Published private(set) var isStandingBy = false
    @Published private(set) var distanceToDestination: Double?
    /// 見守り中の駅の名前
    @Published private(set) var trackingName = ""

    private let manager = CLLocationManager()
    private var trip: TripLogic?
    private var tripDestination: Destination?
    private var backgroundSession: CLBackgroundActivitySession?
    private var tickTimer: Timer?
    private var pendingStop: DispatchWorkItem?
    private var lastPoint: GeoPoint?
    private var wantsAlways = false
    /// 待機中の位置確認で、前回は見張りエリアの中にいたか（入った瞬間だけ見守りを始めるため）
    private var wasInsideWatchArea: Bool?

    /// 伊勢原・鶴巻温泉付近に入って見守りを始めた時刻。
    /// 秦野の 3.5km 圏・2km 圏の知らせは、これから 40 分以内のときだけ使う（地元を移動しただけで鳴らないように）。
    private let armedKey = "armedAt"
    private let armedValidSeconds: TimeInterval = 40 * 60

    func setup() {
        manager.delegate = self
        manager.activityType = .otherNavigation
        manager.pausesLocationUpdatesAutomatically = false
        refreshAuthorization()
        registerWatchAreas()
        // アプリが裏で起こされたときも、すぐ待機を再開する（Apple の決まり）
        ensureStandby()
    }

    /// 「位置情報を許可」ボタン。iPhone の決まりで「使用中のみ」→「常に」の2段階で聞く。
    func requestPermission() {
        switch manager.authorizationStatus {
        case .notDetermined:
            wantsAlways = true
            manager.requestWhenInUseAuthorization()
        case .authorizedWhenInUse:
            manager.requestAlwaysAuthorization()
        default:
            openSettings()
        }
    }

    func openSettings() {
        if let url = URL(string: UIApplication.openSettingsURLString) {
            UIApplication.shared.open(url)
        }
    }

    /// 時間帯に関係なく今すぐ見守りを始める（テストや、遅くなった日のため）
    func startManually() {
        startTrip(reason: "手動で開始")
    }

    /// 降りる駅を変えたとき、見張りエリアを登録し直す
    func destinationChanged() {
        wasInsideWatchArea = nil
        registerWatchAreas()
        EventLog.add("降りる駅を「\(AppSettings.shared.destination.name)」にしました")
    }

    func stopManually() {
        guard isTracking else { return }
        EventLog.add("手動で見守りを終了しました")
        finishTrip(after: 0)
    }

    // MARK: - 待機（省電力の位置確認）

    /// 見守りがオンで「常に」許可があれば、省電力の位置確認を動かしておく。
    /// アプリを開いたとき・見守りをオンにしたとき・アプリが裏で起こされたときに呼ぶ。
    func ensureStandby() {
        guard AppSettings.shared.enabled, manager.authorizationStatus == .authorizedAlways else {
            if isStandingBy || isTracking { stopEverything() }
            return
        }
        if backgroundSession == nil {
            backgroundSession = CLBackgroundActivitySession()
        }
        manager.allowsBackgroundLocationUpdates = true
        if trip == nil { useStandbyAccuracy() }
        manager.startUpdatingLocation()
        if !isStandingBy {
            isStandingBy = true
            EventLog.add("待機を始めました（省電力で位置を確認）")
        }
    }

    private func stopEverything() {
        trip = nil
        isTracking = false
        tickTimer?.invalidate()
        tickTimer = nil
        manager.stopUpdatingLocation()
        manager.allowsBackgroundLocationUpdates = false
        backgroundSession?.invalidate()
        backgroundSession = nil
        isStandingBy = false
        distanceToDestination = nil
        EventLog.add("見守りがオフなので位置の確認を止めました")
    }

    /// 電波・Wi-Fi による大まかな位置（GPS はほぼ使わない）。500m 動いたときだけ知らせてもらう。
    private func useStandbyAccuracy() {
        manager.desiredAccuracy = kCLLocationAccuracyKilometer
        manager.distanceFilter = 500
        manager.showsBackgroundLocationIndicator = false
    }

    /// 見守り中は GPS で細かく
    private func useTripAccuracy() {
        manager.desiredAccuracy = kCLLocationAccuracyBest
        manager.distanceFilter = kCLDistanceFilterNone
        manager.showsBackgroundLocationIndicator = true
    }

    // MARK: - 見張りエリアの登録

    private func refreshAuthorization() {
        authorization = manager.authorizationStatus
        preciseLocation = manager.accuracyAuthorization == .fullAccuracy
    }

    private func registerWatchAreas() {
        let destination = AppSettings.shared.destination
        let areas = destination.watchAreas + destination.stageAreas
        guard manager.authorizationStatus == .authorizedAlways else { return }
        guard CLLocationManager.isMonitoringAvailable(for: CLCircularRegion.self) else {
            EventLog.add("この iPhone では場所の見張りが使えません")
            return
        }
        // 登録済みならそのまま（登録し直すと、届く途中の「エリアに入った」知らせを落とすことがある）
        let registered = Set(manager.monitoredRegions.compactMap { region -> String? in
            guard let circle = region as? CLCircularRegion else { return nil }
            return "\(circle.identifier)-\(Int(circle.radius))"
        })
        let wanted = Set(areas.map { "\($0.id)-\(Int($0.radius))" })
        if registered == wanted { return }

        for region in manager.monitoredRegions {
            manager.stopMonitoring(for: region)
        }
        for area in areas {
            let region = CLCircularRegion(
                center: CLLocationCoordinate2D(latitude: area.center.latitude, longitude: area.center.longitude),
                radius: area.radius,
                identifier: area.id
            )
            region.notifyOnEntry = true
            region.notifyOnExit = false
            manager.startMonitoring(for: region)
        }
    }

    // MARK: - 見守りの開始と終了

    private var armedRecently: Bool {
        guard let armed = UserDefaults.standard.object(forKey: armedKey) as? Date else { return false }
        return Date().timeIntervalSince(armed) < armedValidSeconds
    }

    private func startTrip(reason: String) {
        guard trip == nil else { return }
        pendingStop?.cancel()
        pendingStop = nil

        let destination = AppSettings.shared.destination
        tripDestination = destination
        trackingName = destination.name
        trip = TripLogic(startedAt: Date(), destination: destination.point, nextStation: destination.nextStation)
        UserDefaults.standard.set(Date(), forKey: armedKey)

        if backgroundSession == nil {
            backgroundSession = CLBackgroundActivitySession()
        }
        manager.allowsBackgroundLocationUpdates = true
        useTripAccuracy()
        manager.startUpdatingLocation()

        tickTimer?.invalidate()
        tickTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            self?.tick()
        }
        isTracking = true
        EventLog.add("\(destination.name)までの見守りを開始しました（\(reason)）")
    }

    /// 判定は今すぐ終えるが、GPS は少し細かいまま動かし続ける。
    /// 振動を自動で止める・保護者に通知を送り終えるまでアプリを起こしておくため。
    /// そのあとは待機（省電力）に戻る。
    private func finishTrip(after seconds: TimeInterval) {
        trip = nil
        isTracking = false
        tickTimer?.invalidate()
        tickTimer = nil
        UserDefaults.standard.removeObject(forKey: armedKey)

        pendingStop?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self, self.trip == nil else { return }
            self.distanceToDestination = nil
            self.wasInsideWatchArea = nil
            if AppSettings.shared.enabled {
                self.useStandbyAccuracy()
                EventLog.add("見守りを終えて、待機に戻りました")
            } else {
                self.stopEverything()
            }
        }
        pendingStop = work
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: work)
    }

    private func tick() {
        guard var current = trip else { return }
        let events = current.tick(at: Date())
        trip = current
        handle(events)
    }

    private func handle(_ events: [TripEvent]) {
        let name = tripDestination?.name ?? AppSettings.shared.destination.name
        for event in events {
            switch event {
            case .stage(let n):
                Alarmer.shared.vibrate(.stage(n), station: name)
            case .overshoot:
                EventLog.add("乗り過ごしを検知しました")
                Alarmer.shared.vibrate(.overshoot, station: name)
                ParentNotifier.shared.sendOvershoot(station: name, at: lastPoint)
                finishTrip(after: 60)
            case .arrived:
                EventLog.add("\(name)駅で降りたと判断しました")
                if AppSettings.shared.notifyArrival {
                    ParentNotifier.shared.sendArrived(station: name)
                }
                finishTrip(after: 30)
            case .wrongDirection:
                EventLog.add("\(name)から離れる方向なので見守りを終了しました")
                finishTrip(after: 0)
            case .timeout:
                EventLog.add("1時間たったので見守りを終了しました")
                finishTrip(after: 0)
            }
        }
    }

    /// 待機中の大まかな位置で、見張りエリア（伊勢原・鶴巻温泉など）に入ったかを調べる
    private func checkWatchAreaEntry(_ location: CLLocation) {
        guard location.horizontalAccuracy > 0, location.horizontalAccuracy <= 1500 else { return }
        let point = GeoPoint(latitude: location.coordinate.latitude, longitude: location.coordinate.longitude)
        let destination = AppSettings.shared.destination
        guard let area = destination.watchAreas.first(where: { distanceMeters(point, $0.center) <= $0.radius }) else {
            wasInsideWatchArea = false
            return
        }
        let enteredNow = wasInsideWatchArea == false
        wasInsideWatchArea = true
        guard enteredNow else { return }
        let settings = AppSettings.shared
        guard settings.enabled, settings.isInTimeWindow(Date()) else { return }
        startTrip(reason: "\(area.name)付近に入ったため（位置の確認で検知）")
    }

    // MARK: - CLLocationManagerDelegate

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        refreshAuthorization()
        if manager.authorizationStatus == .authorizedWhenInUse && wantsAlways {
            wantsAlways = false
            manager.requestAlwaysAuthorization()
        }
        registerWatchAreas()
        ensureStandby()
    }

    func locationManager(_ manager: CLLocationManager, didEnterRegion region: CLRegion) {
        let destination = AppSettings.shared.destination
        let settings = AppSettings.shared

        // 予備：秦野の 3.5km 圏・2km 圏に入った
        if let index = destination.stageAreas.firstIndex(where: { $0.id == region.identifier }) {
            let area = destination.stageAreas[index]
            guard settings.enabled, settings.isInTimeWindow(Date()), armedRecently || trip != nil else {
                EventLog.add("\(area.name)に入りました（帰り道の見守り中ではないので何もしません）")
                return
            }
            EventLog.add("\(area.name)に入りました（予備の知らせ）")
            if trip == nil { startTrip(reason: "\(area.name)に入ったため") }
            guard var current = trip else { return }
            let events = current.markStageDue(index + 1, at: Date())
            trip = current
            handle(events)
            return
        }

        let name = destination.watchAreas.first { $0.id == region.identifier }?.name ?? region.identifier
        guard settings.enabled else {
            EventLog.add("\(name)付近に入りました（見守りがオフなので何もしません）")
            return
        }
        guard settings.isInTimeWindow(Date()) else {
            EventLog.add("\(name)付近に入りました（時間外なので何もしません）")
            return
        }
        startTrip(reason: "\(name)付近に入ったため")
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        for location in locations {
            guard trip != nil else {
                checkWatchAreaEntry(location)
                continue
            }
            guard location.horizontalAccuracy > 0, location.horizontalAccuracy <= 150 else { continue }
            let point = GeoPoint(latitude: location.coordinate.latitude, longitude: location.coordinate.longitude)
            lastPoint = point
            distanceToDestination = distanceMeters(point, tripDestination?.point ?? AppSettings.shared.destination.point)

            guard var current = trip else { continue }
            let events = current.update(point: point, speed: location.speed >= 0 ? location.speed : nil, at: location.timestamp)
            trip = current
            handle(events)
        }
    }

    func locationManager(_ manager: CLLocationManager, monitoringDidFailFor region: CLRegion?, withError error: Error) {
        EventLog.add("場所の見張りに失敗しました：\(error.localizedDescription)")
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        EventLog.add("位置情報を取得できませんでした：\(error.localizedDescription)")
    }
}
