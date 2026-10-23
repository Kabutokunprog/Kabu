import Foundation

// 乗り過ごし判定の中身。iPhone の機能に頼らない純粋な計算だけを置き、
// Mac 上のテスト（Tests/TripLogicTests.swift）でそのまま確かめられるようにしている。

struct GeoPoint: Equatable {
    var latitude: Double
    var longitude: Double
}

enum Station {
    static let isehara = GeoPoint(latitude: 35.3960081, longitude: 139.3136066)
    static let tsurumakiOnsen = GeoPoint(latitude: 35.3808409, longitude: 139.2775833)
    static let tokaiDaigakumae = GeoPoint(latitude: 35.3731476, longitude: 139.2712501)
    static let hadano = GeoPoint(latitude: 35.3700428, longitude: 139.2260351)
    static let shibusawa = GeoPoint(latitude: 35.3741177, longitude: 139.1845075)
}

/// 2地点間の距離（メートル）
func distanceMeters(_ a: GeoPoint, _ b: GeoPoint) -> Double {
    let r = 6_371_000.0
    let lat1 = a.latitude * .pi / 180
    let lat2 = b.latitude * .pi / 180
    let dLat = lat2 - lat1
    let dLon = (b.longitude - a.longitude) * .pi / 180
    let h = sin(dLat / 2) * sin(dLat / 2) + cos(lat1) * cos(lat2) * sin(dLon / 2) * sin(dLon / 2)
    return 2 * r * asin(min(1, sqrt(h)))
}

enum TripEvent: Equatable {
    case stage(Int)      // 1〜3回目のアラーム
    case overshoot       // 乗り過ごし
    case arrived         // 秦野で降りた
    case wrongDirection  // 秦野から離れていく（東京方面へ向かっている）
    case timeout
}

struct TripRules {
    /// 秦野駅までの距離がこれ以下になったら鳴らす（東海大学前は秦野から約4.1km）
    var stageDistances: [Double] = [3500, 2000, 800]
    /// 位置が飛んで複数回分が一度に来たときの、鳴らす間隔の最小値
    var minSecondsBetweenStages: TimeInterval = 10
    /// これだけ秦野に近づいたら「秦野へ向かっている」とみなす
    var approachMargin: Double = 300
    /// 近づく前にこれだけ離れたら「反対方向」とみなす
    var wrongDirectionMargin: Double = 1000
    /// 秦野駅にここまで近づいたら「駅を通った」とみなす
    var nearStation: Double = 800
    /// 駅を通ったあと、さらにこれだけ離れたら乗り過ごしの疑い
    var overshootExtra: Double = 1500
    /// 乗り過ごしとみなす速さ（秒速10m = 時速36km。歩きや自転車と区別する）
    var overshootMinSpeed: Double = 10
    /// 渋沢駅にここまで近づいたら乗り過ごし確定
    var shibusawaRadius: Double = 700
    /// 秦野駅のこの範囲に入ってから一定時間たてば「降りた」とみなす
    var arrivedRadius: Double = 500
    var arrivedAfter: TimeInterval = 6 * 60
    var maxTripDuration: TimeInterval = 60 * 60
}

struct TripLogic {
    let rules: TripRules
    let startedAt: Date

    private(set) var finished = false
    private(set) var firedStages = 0
    private(set) var lastDistance: Double?

    private var farthest: Double = 0
    private var closest: Double = .infinity
    private var approachConfirmed = false
    private var stagesDue = 0
    private var lastStageAt: Date?
    private var reachedStationAt: Date?
    private var previous: (point: GeoPoint, at: Date)?

    init(startedAt: Date, rules: TripRules = TripRules()) {
        self.startedAt = startedAt
        self.rules = rules
    }

    /// 新しい位置が届いたとき。speed は iPhone が教えてくれる速さ（秒速m、わからなければ nil）
    mutating func update(point: GeoPoint, speed: Double?, at now: Date) -> [TripEvent] {
        guard !finished else { return [] }

        let d = distanceMeters(point, Station.hadano)
        lastDistance = d
        farthest = max(farthest, d)
        closest = min(closest, d)

        var measuredSpeed = speed ?? -1
        if measuredSpeed < 0, let prev = previous {
            let dt = now.timeIntervalSince(prev.at)
            if dt >= 1 { measuredSpeed = distanceMeters(prev.point, point) / dt }
        }
        previous = (point, now)

        if farthest - d >= rules.approachMargin { approachConfirmed = true }
        if d <= rules.arrivedRadius && reachedStationAt == nil { reachedStationAt = now }

        if !approachConfirmed && firedStages == 0 && d - closest >= rules.wrongDirectionMargin {
            finished = true
            return [.wrongDirection]
        }

        if approachConfirmed {
            let due = rules.stageDistances.filter { d <= $0 }.count
            stagesDue = max(stagesDue, due)
        }

        var events = fireNextStageIfReady(at: now)

        let passedStation = closest <= rules.nearStation
        let nearShibusawa = distanceMeters(point, Station.shibusawa) <= rules.shibusawaRadius
        let runningAway = passedStation && d >= closest + rules.overshootExtra && measuredSpeed >= rules.overshootMinSpeed
        if (nearShibusawa && (passedStation || firedStages > 0)) || runningAway {
            finished = true
            events.append(.overshoot)
            return events
        }

        events += checkTime(at: now)
        return events
    }

    /// 位置が届かなくても数秒ごとに呼ぶ（残っているアラームや「降りた」判定のため）
    mutating func tick(at now: Date) -> [TripEvent] {
        guard !finished else { return [] }
        return fireNextStageIfReady(at: now) + checkTime(at: now)
    }

    private mutating func fireNextStageIfReady(at now: Date) -> [TripEvent] {
        guard firedStages < stagesDue else { return [] }
        if let last = lastStageAt, now.timeIntervalSince(last) < rules.minSecondsBetweenStages { return [] }
        firedStages += 1
        lastStageAt = now
        return [.stage(firedStages)]
    }

    private mutating func checkTime(at now: Date) -> [TripEvent] {
        if let reached = reachedStationAt, now.timeIntervalSince(reached) >= rules.arrivedAfter {
            finished = true
            return [.arrived]
        }
        if now.timeIntervalSince(startedAt) >= rules.maxTripDuration {
            finished = true
            return [.timeout]
        }
        return []
    }
}
