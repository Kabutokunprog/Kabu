import Foundation

/// 「この場所に入ったら GPS を使い始める」という見張りエリア
struct WatchArea: Equatable {
    let id: String
    let name: String
    let center: GeoPoint
    let radius: Double
}

/// 降りる駅と、見守りの始め方
struct Destination: Equatable {
    let name: String
    let point: GeoPoint
    /// 次の駅（わかる場合だけ）
    let nextStation: GeoPoint?
    let watchAreas: [WatchArea]
    /// 画面に出す「いつ見守りを始めるか」の説明
    let startDescription: String
    /// 予備：駅の 3.5km 圏・2km 圏。GPS が止まっていても、ここに入れば iPhone がアプリを起こしてくれる
    var stageAreas: [WatchArea] {
        let key = "\(Int(point.latitude * 10000))-\(Int(point.longitude * 10000))"
        return [
            WatchArea(id: "stage1-\(key)", name: "\(name)駅の3.5km圏", center: point, radius: 3500),
            WatchArea(id: "stage2-\(key)", name: "\(name)駅の2km圏", center: point, radius: 2000),
        ]
    }

    /// 秦野駅（いつもの設定）。東京方面から来るときだけ見守るよう、伊勢原・鶴巻温泉で見張る。
    static let hadano = Destination(
        name: "秦野",
        point: Station.hadano,
        nextStation: Station.shibusawa,
        watchAreas: [
            WatchArea(id: "isehara", name: "伊勢原駅", center: Station.isehara, radius: 1500),
            WatchArea(id: "tsurumaki", name: "鶴巻温泉駅", center: Station.tsurumakiOnsen, radius: 1200),
        ],
        startDescription: "伊勢原付近へ入ると"
    )

    /// ほかの駅：駅から 8km の範囲に入ったら見守りを始める。
    /// どちらの方向から来ても見張り、駅から離れていく場合はすぐやめる。
    static func custom(name: String, point: GeoPoint) -> Destination {
        let key = "\(Int(point.latitude * 10000))-\(Int(point.longitude * 10000))"
        return Destination(
            name: name,
            point: point,
            nextStation: nil,
            watchAreas: [
                WatchArea(id: "custom-\(key)", name: "\(name)駅の8km圏", center: point, radius: customWatchRadius),
            ],
            startDescription: "\(name)駅の8km手前に入ると"
        )
    }

    static let customWatchRadius: Double = 8000
}
