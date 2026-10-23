import Foundation
import AudioToolbox
import UserNotifications

enum AlarmKind {
    case stage(Int)
    case overshoot

    var title: String {
        switch self {
        case .stage(1): return "もうすぐ秦野（あと約3分）"
        case .stage(2): return "次は秦野！降りる準備を"
        case .stage(_): return "秦野に着きます！降りて！"
        case .overshoot: return "秦野を過ぎました！次の駅で降りて戻ろう"
        }
    }

    /// 振動のリズム。0.7秒ごとに 1=ブルッ / 0=休み をくり返す。
    /// 1回目は「ブルッ」、2回目は「ブルッブルッ」、3回目は「ブルッブルッブルッ」。
    var pattern: [Bool] {
        switch self {
        case .stage(1): return [true, false, false, false]
        case .stage(2): return [true, true, false, false, false]
        case .stage(_): return [true, true, true, false, false, false]
        case .overshoot: return [true]
        }
    }

    /// 自動で止めるまでの秒数
    var vibrateSeconds: TimeInterval {
        switch self {
        case .stage(1), .stage(2): return 20
        case .stage(_), .overshoot: return 30
        }
    }

    var logName: String {
        switch self {
        case .stage(let n): return "\(n)回目のバイブ"
        case .overshoot: return "乗り過ごしのバイブ"
        }
    }
}

/// 音は出さず、振動だけで知らせる。
/// 見守り中は GPS のおかげでアプリが裏でも動き続けているので、その間に振動をくり返す。
/// あわせて「止める」ボタン付きの通知も出す（通知は無音ファイルを使うので音は鳴らない）。
final class Alarmer: ObservableObject {
    static let shared = Alarmer()

    static let notificationCategory = "HADANO_ALARM"
    static let stopActionID = "STOP"

    @Published private(set) var isVibrating = false
    @Published private(set) var notificationsAllowed = false

    private var timer: Timer?
    private var step = 0
    private var endAt = Date.distantPast
    private var pattern: [Bool] = []
    private let tickSeconds: TimeInterval = 0.7

    func registerNotificationActions() {
        let stop = UNNotificationAction(identifier: Self.stopActionID, title: "止める", options: [])
        let category = UNNotificationCategory(identifier: Self.notificationCategory, actions: [stop], intentIdentifiers: [], options: [])
        UNUserNotificationCenter.current().setNotificationCategories([category])
    }

    func requestNotificationPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { granted, _ in
            DispatchQueue.main.async { self.notificationsAllowed = granted }
        }
    }

    func refreshNotificationPermission() {
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            let ok = settings.authorizationStatus == .authorized
            DispatchQueue.main.async { self.notificationsAllowed = ok }
        }
    }

    func vibrate(_ kind: AlarmKind) {
        DispatchQueue.main.async { self.start(kind) }
    }

    func stopCurrent() {
        DispatchQueue.main.async {
            guard self.timer != nil else { return }
            self.timer?.invalidate()
            self.timer = nil
            self.isVibrating = false
            UNUserNotificationCenter.current().removeAllDeliveredNotifications()
        }
    }

    private func start(_ kind: AlarmKind) {
        // 前のバイブが続いていたら止めてから次を始める
        timer?.invalidate()
        pattern = kind.pattern
        step = 0
        endAt = Date().addingTimeInterval(kind.vibrateSeconds)
        isVibrating = true

        let t = Timer(timeInterval: tickSeconds, repeats: true) { [weak self] _ in
            self?.tick()
        }
        RunLoop.main.add(t, forMode: .common)
        timer = t
        tick()

        postNotification(kind)
        EventLog.add("\(kind.logName)を始めました")
    }

    private func tick() {
        guard Date() < endAt else {
            stopCurrent()
            return
        }
        if pattern[step % pattern.count] {
            AudioServicesPlaySystemSound(kSystemSoundID_Vibrate)
        }
        step += 1
    }

    private func postNotification(_ kind: AlarmKind) {
        let content = UNMutableNotificationContent()
        content.title = kind.title
        content.body = "「止める」で振動を止められます。"
        content.categoryIdentifier = Self.notificationCategory
        // 無音のファイルを指定：音は鳴らないが、通知としての振動は出る
        content.sound = UNNotificationSound(named: UNNotificationSoundName("silence.wav"))
        content.interruptionLevel = .active
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }
}
