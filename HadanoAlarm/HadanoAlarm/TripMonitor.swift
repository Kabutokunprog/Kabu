import Foundation
import CoreLocation
import UIKit

/// 位置情報の見張り役。
/// ふだんは iPhone の省エネな「場所の見張り（ジオフェンス）」だけを使い、
/// 設定した時間帯に、降りる駅の手前の見張りエリアへ入ったときだけ GPS を使い始める。
final class TripMonitor: NSObject, ObservableObject, CLLocationManagerDelegate {
    static let shared = TripMonitor()

    @Published private(set) var authorization: CLAuthorizationStatus = .notDetermined
    @Published private(set) var preciseLocation = true
    @Published private(set) var isTracking = false
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

    func setup() {
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
        manager.distanceFilter = kCLDistanceFilterNone
        manager.activityType = .otherNavigation
        manager.pausesLocationUpdatesAutomatically = false
        refreshAuthorization()
        registerWatchAreas()
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
        registerWatchAreas()
        EventLog.add("降りる駅を「\(AppSettings.shared.destination.name)」にしました")
    }

    func stopManually() {
        guard isTracking else { return }
        EventLog.add("手動で見守りを終了しました")
        finishTrip(after: 0)
    }

    // MARK: - 見張りエリアの登録

    private func refreshAuthorization() {
        authorization = manager.authorizationStatus
        preciseLocation = manager.accuracyAuthorization == .fullAccuracy
    }

    private func registerWatchAreas() {
        let watchAreas = AppSettings.shared.destination.watchAreas
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
        let wanted = Set(watchAreas.map { "\($0.id)-\(Int($0.radius))" })
        if registered == wanted { return }

        for region in manager.monitoredRegions {
            manager.stopMonitoring(for: region)
        }
        for area in watchAreas {
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

    private func startTrip(reason: String) {
        guard trip == nil else { return }
        pendingStop?.cancel()
        pendingStop = nil

        let destination = AppSettings.shared.destination
        tripDestination = destination
        trackingName = destination.name
        trip = TripLogic(startedAt: Date(), destination: destination.point, nextStation: destination.nextStation)
        if backgroundSession == nil {
            backgroundSession = CLBackgroundActivitySession()
        }
        manager.allowsBackgroundLocationUpdates = true
        manager.showsBackgroundLocationIndicator = true
        manager.startUpdatingLocation()

        tickTimer?.invalidate()
        tickTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            self?.tick()
        }
        isTracking = true
        EventLog.add("\(destination.name)までの見守りを開始しました（\(reason)）")
    }

    /// 判定は今すぐ終えるが、GPS は少し動かし続ける。
    /// アラームを自動で止める・保護者に通知を送り終えるまでアプリを起こしておくため。
    private func finishTrip(after seconds: TimeInterval) {
        trip = nil
        isTracking = false
        tickTimer?.invalidate()
        tickTimer = nil

        pendingStop?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self, self.trip == nil else { return }
            self.manager.stopUpdatingLocation()
            self.manager.allowsBackgroundLocationUpdates = false
            self.backgroundSession?.invalidate()
            self.backgroundSession = nil
            self.distanceToDestination = nil
            EventLog.add("GPS を止めました")
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

    // MARK: - CLLocationManagerDelegate

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        refreshAuthorization()
        if manager.authorizationStatus == .authorizedWhenInUse && wantsAlways {
            wantsAlways = false
            manager.requestAlwaysAuthorization()
        }
        registerWatchAreas()
    }

    func locationManager(_ manager: CLLocationManager, didEnterRegion region: CLRegion) {
        let name = AppSettings.shared.destination.watchAreas.first { $0.id == region.identifier }?.name ?? region.identifier
        let settings = AppSettings.shared
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
