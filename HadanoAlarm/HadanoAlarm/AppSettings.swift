import Foundation

final class AppSettings: ObservableObject {
    static let shared = AppSettings()

    private let defaults = UserDefaults.standard

    /// 見守り全体のオン・オフ
    @Published var enabled: Bool { didSet { defaults.set(enabled, forKey: "enabled") } }
    /// 見守りする時間帯（0時からの分。17:00 = 1020）
    @Published var startMinutes: Int { didSet { defaults.set(startMinutes, forKey: "startMinutes") } }
    @Published var endMinutes: Int { didSet { defaults.set(endMinutes, forKey: "endMinutes") } }
    /// 見守りする曜日（1=日曜 … 7=土曜）
    @Published var weekdays: Set<Int> { didSet { defaults.set(Array(weekdays).sorted(), forKey: "weekdays") } }
    /// 保護者への通知で使う呼び名
    @Published var childName: String { didSet { defaults.set(childName, forKey: "childName") } }
    /// 秦野で降りたときも保護者に知らせるか
    @Published var notifyArrival: Bool { didSet { defaults.set(notifyArrival, forKey: "notifyArrival") } }
    /// 保護者のスマホの ntfy アプリで登録する「トピック名」（合言葉のようなもの）
    let ntfyTopic: String

    private init() {
        defaults.register(defaults: [
            "enabled": true,
            "startMinutes": 17 * 60,
            "endMinutes": 20 * 60,
            "weekdays": [2, 3, 4, 5, 6],
            "childName": "娘",
            "notifyArrival": true,
        ])
        enabled = defaults.bool(forKey: "enabled")
        startMinutes = defaults.integer(forKey: "startMinutes")
        endMinutes = defaults.integer(forKey: "endMinutes")
        weekdays = Set((defaults.array(forKey: "weekdays") as? [Int]) ?? [2, 3, 4, 5, 6])
        childName = defaults.string(forKey: "childName") ?? "娘"
        notifyArrival = defaults.bool(forKey: "notifyArrival")

        if let saved = defaults.string(forKey: "ntfyTopic") {
            ntfyTopic = saved
        } else {
            let letters = Array("abcdefghijkmnpqrstuvwxyz23456789")
            let random = String((0..<12).map { _ in letters.randomElement()! })
            ntfyTopic = "hadano-\(random)"
            defaults.set(ntfyTopic, forKey: "ntfyTopic")
        }
    }

    func isInTimeWindow(_ date: Date) -> Bool {
        let parts = Calendar.current.dateComponents([.weekday, .hour, .minute], from: date)
        guard weekdays.contains(parts.weekday ?? 0) else { return false }
        let now = (parts.hour ?? 0) * 60 + (parts.minute ?? 0)
        if startMinutes <= endMinutes {
            return now >= startMinutes && now < endMinutes
        }
        // 日付をまたぐ設定（例：22:00〜1:00）
        return now >= startMinutes || now < endMinutes
    }

    static let weekdayNames = ["日", "月", "火", "水", "木", "金", "土"]

    var weekdaysText: String {
        if weekdays.count == 7 { return "毎日" }
        if weekdays == [2, 3, 4, 5, 6] { return "平日" }
        return (1...7).filter { weekdays.contains($0) }.map { Self.weekdayNames[$0 - 1] }.joined(separator: "・")
    }

    static func timeText(_ minutes: Int) -> String {
        String(format: "%d:%02d", minutes / 60, minutes % 60)
    }
}
