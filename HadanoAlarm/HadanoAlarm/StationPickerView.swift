import SwiftUI
import MapKit

/// 秦野以外の駅を、駅名で検索して選ぶ画面
struct StationPickerView: View {
    @ObservedObject private var settings = AppSettings.shared
    @Environment(\.dismiss) private var dismiss

    @State private var query = ""
    @State private var results: [MKMapItem] = []
    @State private var searching = false
    @State private var message: String?

    var body: some View {
        List {
            Section {
                HStack {
                    TextField("駅名（例：新百合ヶ丘）", text: $query)
                        .submitLabel(.search)
                        .onSubmit(search)
                    Button("検索", action: search)
                        .disabled(query.trimmingCharacters(in: .whitespaces).isEmpty || searching)
                }
            } footer: {
                if let message { Text(message) }
            }

            if searching {
                ProgressView()
            }

            ForEach(Array(results.enumerated()), id: \.offset) { _, item in
                Button {
                    choose(item)
                } label: {
                    VStack(alignment: .leading) {
                        Text(item.name ?? "名前なし").foregroundStyle(.primary)
                        if let address = item.placemark.title {
                            Text(address).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .navigationTitle("駅を選ぶ")
    }

    private func search() {
        let word = query.trimmingCharacters(in: .whitespaces)
        guard !word.isEmpty else { return }
        searching = true
        message = nil
        Task {
            let request = MKLocalSearch.Request()
            request.naturalLanguageQuery = word.hasSuffix("駅") ? word : word + "駅"
            request.resultTypes = .pointOfInterest
            // 日本全体を検索範囲にする
            request.region = MKCoordinateRegion(
                center: CLLocationCoordinate2D(latitude: 36.5, longitude: 138.0),
                span: MKCoordinateSpan(latitudeDelta: 20, longitudeDelta: 20)
            )
            do {
                let response = try await MKLocalSearch(request: request).start()
                results = Array(response.mapItems.prefix(10))
                if results.isEmpty { message = "見つかりませんでした。別の書き方で試してください。" }
            } catch {
                results = []
                message = "見つかりませんでした。別の書き方で試してください。"
            }
            searching = false
        }
    }

    private func choose(_ item: MKMapItem) {
        var name = item.name ?? query
        // 「新百合ヶ丘駅」→「新百合ヶ丘」（画面で「〜駅」と付けるため）
        if name.hasSuffix("駅") { name.removeLast() }
        let c = item.placemark.coordinate
        settings.setCustomStation(name: name, point: GeoPoint(latitude: c.latitude, longitude: c.longitude))
        TripMonitor.shared.destinationChanged()
        dismiss()
    }
}
