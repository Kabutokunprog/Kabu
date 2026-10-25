import Foundation
import UIKit

/// 保護者のスマホへ通知を送る。無料の通知サービス ntfy (https://ntfy.sh) を使う。
/// 保護者は ntfy アプリを入れて、設定画面に出ている「トピック名」を登録しておく。
final class ParentNotifier {
    static let shared = ParentNotifier()

    private let maxAttempts = 4
    private let retryDelay: TimeInterval = 10

    func sendOvershoot(station: String, at point: GeoPoint?) {
        let name = AppSettings.shared.childName
        var message = "\(name)が\(station)駅を乗り過ごしたようです。電話して起こしてあげてください。"
        var mapURL: URL?
        if let p = point {
            mapURL = URL(string: "https://maps.apple.com/?q=\(p.latitude),\(p.longitude)")
            message += "\n地図を開くと今いる場所がわかります。"
        }
        send(title: "乗り過ごし注意", message: message, priority: 5, tags: ["rotating_light"], click: mapURL)
    }

    func sendArrived(station: String) {
        let name = AppSettings.shared.childName
        send(title: "\(station)に着きました", message: "\(name)が\(station)駅で降りました。", priority: 3, tags: ["white_check_mark"], click: nil)
    }

    func sendTest() {
        send(title: "テスト通知", message: "秦野アラームからのテスト通知です。これが届けば準備OKです。", priority: 3, tags: ["bell"], click: nil)
    }

    private func send(title: String, message: String, priority: Int, tags: [String], click: URL?, attempt: Int = 1) {
        var body: [String: Any] = [
            "topic": AppSettings.shared.ntfyTopic,
            "title": title,
            "message": message,
            "priority": priority,
            "tags": tags,
        ]
        if let click { body["click"] = click.absoluteString }

        var request = URLRequest(url: URL(string: "https://ntfy.sh/")!)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        request.timeoutInterval = 15

        // 画面を閉じていても送り終わるまで待ってもらう
        var taskID = UIBackgroundTaskIdentifier.invalid
        taskID = UIApplication.shared.beginBackgroundTask(withName: "parent-notify") {
            UIApplication.shared.endBackgroundTask(taskID)
        }

        URLSession.shared.dataTask(with: request) { [weak self] _, response, error in
            defer { UIApplication.shared.endBackgroundTask(taskID) }
            guard let self else { return }
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            if error == nil && status == 200 {
                EventLog.add("保護者へ通知しました：\(title)")
                return
            }
            let reason = error?.localizedDescription ?? "応答コード \(status)"
            if attempt < self.maxAttempts {
                EventLog.add("保護者への通知に失敗（\(reason)）。\(Int(self.retryDelay))秒後にもう一度送ります")
                DispatchQueue.main.asyncAfter(deadline: .now() + self.retryDelay) {
                    self.send(title: title, message: message, priority: priority, tags: tags, click: click, attempt: attempt + 1)
                }
            } else {
                EventLog.add("保護者への通知を送れませんでした（\(reason)）")
            }
        }.resume()
    }
}
