import Foundation

// 乗り過ごし判定のテスト。電車の動きをまねた位置データを流し込んで、
// 期待どおりのタイミングで知らせが出るかを確かめる。
// 実行方法（Mac のターミナル）:
//   swiftc HadanoAlarm/TripLogic.swift Tests/main.swift -o /tmp/tripTests && /tmp/tripTests

var failures = 0

func check(_ condition: Bool, _ message: String) {
    if condition {
        print("  OK   \(message)")
    } else {
        print("  NG   \(message)")
        failures += 1
    }
}

func lerp(_ a: GeoPoint, _ b: GeoPoint, _ t: Double) -> GeoPoint {
    GeoPoint(latitude: a.latitude + (b.latitude - a.latitude) * t,
             longitude: a.longitude + (b.longitude - a.longitude) * t)
}

/// 駅をつないだ線の上を、決まった速さで進む動きを作る
struct Leg {
    let from: GeoPoint
    let to: GeoPoint
    let speed: Double  // 秒速 m（0 なら停車）
    let stopSeconds: Double
}

struct Sample {
    let point: GeoPoint
    let at: Date
    let speed: Double
}

func simulate(_ legs: [Leg], every interval: Double = 2) -> [Sample] {
    var samples: [Sample] = []
    var clock = Date(timeIntervalSince1970: 1_700_000_000)
    for leg in legs {
        if leg.speed == 0 {
            var waited = 0.0
            while waited < leg.stopSeconds {
                samples.append(Sample(point: leg.from, at: clock, speed: 0))
                clock += interval
                waited += interval
            }
            continue
        }
        let length = distanceMeters(leg.from, leg.to)
        var traveled = 0.0
        while traveled < length {
            samples.append(Sample(point: lerp(leg.from, leg.to, traveled / length), at: clock, speed: leg.speed))
            clock += interval
            traveled += leg.speed * interval
        }
    }
    return samples
}

struct Result {
    var events: [(TripEvent, Double)] = []  // (知らせ, そのときの秦野までの距離)
}

func run(_ samples: [Sample], drop: ((Sample) -> Bool)? = nil) -> Result {
    var logic = TripLogic(startedAt: samples[0].at)
    var result = Result()
    for s in samples {
        let d = distanceMeters(s.point, Station.hadano)
        let events: [TripEvent]
        if let drop, drop(s) {
            events = logic.tick(at: s.at)
        } else {
            events = logic.update(point: s.point, speed: s.speed, at: s.at)
        }
        for e in events { result.events.append((e, d)) }
        if logic.finished { break }
    }
    return result
}

let train = 22.0  // 時速約80km
let walkAwayPoint = GeoPoint(latitude: 35.3600, longitude: 139.2260)  // 秦野駅の南 約1.1km

let homeRide: [Leg] = [
    Leg(from: Station.isehara, to: Station.tsurumakiOnsen, speed: train, stopSeconds: 0),
    Leg(from: Station.tsurumakiOnsen, to: Station.tsurumakiOnsen, speed: 0, stopSeconds: 30),
    Leg(from: Station.tsurumakiOnsen, to: Station.tokaiDaigakumae, speed: 15, stopSeconds: 0),
    Leg(from: Station.tokaiDaigakumae, to: Station.tokaiDaigakumae, speed: 0, stopSeconds: 30),
    Leg(from: Station.tokaiDaigakumae, to: Station.hadano, speed: train, stopSeconds: 0),
    Leg(from: Station.hadano, to: Station.hadano, speed: 0, stopSeconds: 60),
]

print("1. 秦野で降りて歩いて帰る")
do {
    let r = run(simulate(homeRide + [Leg(from: Station.hadano, to: walkAwayPoint, speed: 1.2, stopSeconds: 0)]))
    let stages = r.events.compactMap { e, d -> (Int, Double)? in
        if case .stage(let n) = e { return (n, d) } else { return nil }
    }
    check(stages.map { $0.0 } == [1, 2, 3], "3回とも順番に知らせる（\(stages.map { $0.0 })）")
    check(stages.allSatisfy { $0.1 < distanceMeters(Station.tokaiDaigakumae, Station.hadano) }, "どれも東海大学前を過ぎてから")
    check(stages.allSatisfy { $0.1 > 100 }, "どれも秦野に着く前（距離 \(stages.map { Int($0.1) }) m）")
    check(r.events.contains { $0.0 == .arrived }, "降りたと判断する")
    check(!r.events.contains { $0.0 == .overshoot }, "乗り過ごしとは言わない")
}

print("2. 寝過ごして渋沢方面へ")
do {
    let ride = homeRide + [Leg(from: Station.hadano, to: Station.shibusawa, speed: train, stopSeconds: 0)]
    let r = run(simulate(ride))
    check(r.events.filter { if case .stage = $0.0 { return true }; return false }.count == 3, "その前に3回知らせている")
    let over = r.events.first { $0.0 == .overshoot }
    check(over != nil, "乗り過ごしを検知する")
    if let over { check(over.1 < 2500, "渋沢に着く前に気づく（秦野から \(Int(over.1)) m）") }
    check(!r.events.contains { $0.0 == .arrived }, "降りたとは言わない")
}

print("3. 夕方に東京方面へ出かける（反対方向）")
do {
    let away = GeoPoint(latitude: 35.4300, longitude: 139.3900)  // 伊勢原より東
    let r = run(simulate([Leg(from: Station.isehara, to: away, speed: train, stopSeconds: 0)]))
    check(r.events.map { $0.0 } == [.wrongDirection], "知らせず見守りをやめる（\(r.events.map { $0.0 })）")
}

print("4. 東海大学前から先で位置が取れない時間がある")
do {
    let samples = simulate(homeRide + [Leg(from: Station.hadano, to: walkAwayPoint, speed: 1.2, stopSeconds: 0)])
    let r = run(samples) { s in
        let d = distanceMeters(s.point, Station.hadano)
        return d < 3800 && d > 600  // この間は位置が届かない
    }
    let stages = r.events.compactMap { e, _ -> Int? in
        if case .stage(let n) = e { return n } else { return nil }
    }
    check(stages == [1, 2, 3], "それでも3回とも知らせる（\(stages)）")
}

print("5. 伊勢原付近で長く止まったまま")
do {
    let r = run(simulate([Leg(from: Station.isehara, to: Station.isehara, speed: 0, stopSeconds: 61 * 60)], every: 10))
    check(r.events.map { $0.0 } == [.timeout], "1時間で見守りをやめる（\(r.events.map { $0.0 })）")
}

print(failures == 0 ? "\nすべて OK" : "\nNG が \(failures) 件あります")
exit(failures == 0 ? 0 : 1)
