import Foundation

/// アプリが何をしたかの記録。うまく動かなかったときに原因を調べるために残す。
final class EventLog: ObservableObject {
    static let shared = EventLog()

    @Published private(set) var entries: [String]

    private let key = "eventLog"
    private let maxEntries = 200
    private let formatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "ja_JP")
        f.dateFormat = "M/d HH:mm:ss"
        return f
    }()

    private init() {
        entries = UserDefaults.standard.stringArray(forKey: key) ?? []
    }

    static func add(_ message: String) {
        DispatchQueue.main.async { shared.append(message) }
    }

    func clear() {
        entries = []
        UserDefaults.standard.set(entries, forKey: key)
    }

    private func append(_ message: String) {
        entries.insert("\(formatter.string(from: Date()))  \(message)", at: 0)
        if entries.count > maxEntries { entries.removeLast(entries.count - maxEntries) }
        UserDefaults.standard.set(entries, forKey: key)
    }
}
