import AppKit
import SwiftUI

// Native menu-bar UI with an allowlisted local snapshot helper.

enum ProviderID: String, CaseIterable, Identifiable {
    case claude = "Claude"
    case codex = "Codex"
    case grok = "Grok"
    case gemini = "Gemini"

    var id: String { rawValue }

    var icon: String {
        switch self {
        case .claude: "sparkles"
        case .codex: "square.stack.3d.up.fill"
        case .grok: "xmark"
        case .gemini: "diamond.fill"
        }
    }

    var appIconResourceName: String {
        "ProviderIcon-\(rawValue.lowercased())"
    }

    var appIconResourceExtension: String {
        self == .codex ? "png" : "jpg"
    }

    var tint: Color {
        switch self {
        case .claude: Color(red: 0.83, green: 0.39, blue: 0.22)
        case .codex: Color(red: 0.12, green: 0.65, blue: 0.52)
        case .grok: .primary
        case .gemini: Color(red: 0.32, green: 0.49, blue: 0.94)
        }
    }
}

enum AuthHealth: String {
    case ready = "정상"
    case expiring = "갱신 필요"
    case unavailable = "전환 불가"

    var color: Color {
        switch self {
        case .ready: .green
        case .expiring: .orange
        case .unavailable: .red
        }
    }
}

enum DataOrigin: String, Hashable {
    case live = "LIVE"
    case demo = "DEMO"

    var color: Color { self == .live ? .green : .orange }
}

struct Account: Identifiable, Hashable {
    let id: String
    let name: String
    let email: String
    let plan: String
    let health: AuthHealth
    let switchable: Bool
    let usage: [UsageWindow]
    var benefits: [BenefitBalance] = []
    var origin: DataOrigin = .demo
    var grokHome: String? = nil

    var recommendationScore: Double {
        guard !usage.isEmpty else { return .infinity }
        let weighted = usage.reduce(into: (total: 0.0, weight: 0.0)) { result, window in
            let weight = window.label.contains("주간") || window.label.contains("일간") ? 2.0 : 1.0
            result.total += Double(window.usedPercent) * weight
            result.weight += weight
        }
        let expiringCreditBonus = benefits.contains(where: \.isExpiringSoon) ? 6.0 : 0.0
        return weighted.total / weighted.weight - expiringCreditBonus
    }

    var recommendationReason: String {
        let limits = usage.prefix(2).map { "\($0.label) \(100 - $0.usedPercent)% 남음 · \($0.resetsIn) 후 초기화" }
        if let benefit = benefits.first(where: \.isExpiringSoon) {
            return (limits + ["\(benefit.label) \(benefit.amount) 우선 사용 권장"]).joined(separator: " / ")
        }
        return limits.joined(separator: " / ")
    }
}

struct BenefitBalance: Hashable {
    let label: String
    let amount: String
    let detail: String
    var isExpiringSoon = false
}

struct UsageWindow: Hashable {
    let label: String
    let usedPercent: Int
    let resetsIn: String
}

private func quotaSlots(for usage: [UsageWindow], count: Int = 2) -> [UsageWindow?] {
    let available = usage.prefix(count).map(Optional.some)
    return available + Array(repeating: nil, count: max(0, count - available.count))
}

private enum PrototypeProcessError: Error {
    case failed(Int32, Data)
}

struct ProviderState: Identifiable {
    var id: ProviderID
    var activeAccountID: String
    var accounts: [Account]
    var checkedAt: String
    var note: String?

    var activeAccount: Account? {
        accounts.first { $0.id == activeAccountID }
    }

    var highestUsage: Int {
        usage.map(\.usedPercent).max() ?? 0
    }

    var usage: [UsageWindow] {
        activeAccount?.usage ?? []
    }

    var recommendedAccount: Account? {
        let candidates = accounts.filter {
            $0.origin == .live && $0.health == .ready && !$0.usage.isEmpty
        }
        return candidates.min { $0.recommendationScore < $1.recommendationScore }
    }

    var recommendationHoldReason: String {
        let hasReadableLiveUsage = accounts.contains {
            $0.origin == .live && $0.health == .ready && !$0.usage.isEmpty
        }
        return hasReadableLiveUsage
            ? "추천 보류 · 전환 가능한 계정이 없음"
            : "추천 보류 · LIVE 사용량을 읽을 수 없음"
    }
}

@MainActor
final class PrototypeStore: ObservableObject {
    @Published var providers: [ProviderState]
    @Published var selectedProvider: ProviderID = .claude
    @Published var lastEvent: String
    @Published var dataMode: String
    @Published var switchingAccountID: String?
    private let demoOnly: Bool

    init() {
        demoOnly = CommandLine.arguments.contains("--demo-only") ||
            ProcessInfo.processInfo.environment["SWITCHBOARD_DEMO_ONLY"] == "1"
        if demoOnly {
            providers = Self.samples
            dataMode = "DEMO"
            lastEvent = "DEMO 전용 · 실계정은 읽지 않았습니다"
        } else {
            providers = Self.unavailableProviders(note: "LIVE 상태를 읽는 중")
            dataMode = "LIVE"
            lastEvent = "LIVE 상태를 읽는 중…"
            refreshLiveData()
        }
    }

    func refreshLiveData() {
        guard !demoOnly else { return }
        guard let script = Bundle.main.url(forResource: "live_snapshot", withExtension: "py") else {
            providers = Self.unavailableProviders(note: "LIVE snapshot 도우미를 찾을 수 없음")
            dataMode = "LIVE"
            lastEvent = "LIVE 조회 실패 · snapshot 도우미 없음"
            return
        }

        providers = Self.unavailableProviders(note: "LIVE 상태를 읽는 중")
        dataMode = "LIVE"
        lastEvent = "실데이터 읽는 중…"
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result = Self.runPython(script: script.path, arguments: [])
            DispatchQueue.main.async {
                guard let self else { return }
                guard case let .success(data) = result,
                      let snapshot = try? JSONDecoder().decode(LiveSnapshot.self, from: data)
                else {
                    self.providers = Self.unavailableProviders(note: "LIVE snapshot 조회 실패")
                    self.dataMode = "LIVE"
                    self.lastEvent = "LIVE 조회 실패 · 다시 시도하세요"
                    return
                }
                self.apply(snapshot: snapshot)
            }
        }
    }

    private func apply(snapshot: LiveSnapshot) {
        providers = merge(snapshot: snapshot)
        let liveCount = providers.flatMap(\.accounts).filter { $0.origin == .live }.count
        dataMode = "LIVE"
        lastEvent = "✓ 실계정 \(liveCount)개 로드"
    }

    nonisolated private static func runPython(script: String, arguments: [String]) -> Result<Data, Error> {
        let process = Process()
        let output = Pipe()
        let pythonCandidates = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
        let python = pythonCandidates.first { FileManager.default.isExecutableFile(atPath: $0) } ?? "/usr/bin/python3"
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = [script] + arguments
        process.standardOutput = output
        process.standardError = Pipe()
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = environment
        do {
            try process.run()
            process.waitUntilExit()
            let data = output.fileHandleForReading.readDataToEndOfFile()
            guard process.terminationStatus == 0 else {
                return .failure(PrototypeProcessError.failed(process.terminationStatus, data))
            }
            return .success(data)
        } catch {
            return .failure(error)
        }
    }

    private func merge(snapshot: LiveSnapshot) -> [ProviderState] {
        ProviderID.allCases.map { id in
            guard let liveProvider = snapshot.providers.first(where: { $0.id == id.rawValue.lowercased() }) else {
                return Self.unavailableProvider(id: id, note: "LIVE 공급자 응답 없음")
            }
            return ProviderState(
                id: id,
                activeAccountID: liveProvider.activeAccountID,
                accounts: liveProvider.accounts
                    .filter(\.isLiveOrigin)
                    .map { $0.account },
                checkedAt: liveProvider.checkedAt.hasPrefix("CACHE") ? liveProvider.checkedAt : "LIVE · \(liveProvider.checkedAt)",
                note: liveProvider.note,
            )
        }
    }

    private static func unavailableProviders(note: String) -> [ProviderState] {
        ProviderID.allCases.map { unavailableProvider(id: $0, note: note) }
    }

    private static func unavailableProvider(id: ProviderID, note: String) -> ProviderState {
        ProviderState(
            id: id,
            activeAccountID: "",
            accounts: [],
            checkedAt: "LIVE 조회 불가",
            note: note
        )
    }

    func provider(_ id: ProviderID) -> ProviderState {
        providers.first { $0.id == id }!
    }

    func switchAccount(provider id: ProviderID, accountID: String) {
        guard switchingAccountID == nil else { return }
        guard let providerIndex = providers.firstIndex(where: { $0.id == id }),
              let account = providers[providerIndex].accounts.first(where: { $0.id == accountID })
        else { return }

        guard account.origin == .live else {
            selectedProvider = id
            lastEvent = "DEMO · 예시 계정은 실제 전환하지 않습니다"
            return
        }

        guard (id == .claude || id == .codex), account.health == .ready, account.switchable else {
            selectedProvider = id
            lastEvent = "\(id.rawValue) · \(account.name)은 현재 전환할 수 없습니다"
            return
        }

        selectedProvider = id
        switchingAccountID = accountID
        lastEvent = "\(id.rawValue) / \(account.name) 전환 중…"
        guard let manager = Bundle.main.url(forResource: "account_manager", withExtension: "py") else {
            switchingAccountID = nil
            lastEvent = "전환 도우미가 앱에 포함되지 않았습니다"
            return
        }
        let commandID = accountID.replacingOccurrences(of: "\(id.rawValue.lowercased())-", with: "", options: [.anchored])
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result = Self.runPython(
                script: manager.path,
                arguments: ["switch-provider", id.rawValue.lowercased(), commandID, "--json"]
            )
            DispatchQueue.main.async {
                self?.finishSwitch(result: result, provider: id, account: account)
            }
        }
    }

    private func finishSwitch(result: Result<Data, Error>, provider: ProviderID, account: Account) {
        let data: Data?
        switch result {
        case let .success(output):
            data = output
        case let .failure(PrototypeProcessError.failed(_, output)):
            data = output
        case .failure:
            data = nil
        }
        let decoded = data.flatMap { try? JSONDecoder().decode(SwitchResponse.self, from: $0) }
        guard let response = decoded,
              response.ok,
              response.provider.lowercased() == provider.rawValue.lowercased(),
              response.requestedAccountID == response.activeAccountID
        else {
            switchingAccountID = nil
            lastEvent = decoded?.message ?? "\(provider.rawValue) 전환 실패 · 상태를 다시 확인하세요"
            return
        }

        guard let script = Bundle.main.url(forResource: "live_snapshot", withExtension: "py") else {
            switchingAccountID = nil
            lastEvent = "\(provider.rawValue) 전환 결과를 확인할 수 없습니다"
            return
        }
        lastEvent = "\(provider.rawValue) 전환 확인 중…"
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let refresh = Self.runPython(script: script.path, arguments: [])
            DispatchQueue.main.async {
                guard let self else { return }
                self.switchingAccountID = nil
                guard case let .success(snapshotData) = refresh,
                      let snapshot = try? JSONDecoder().decode(LiveSnapshot.self, from: snapshotData),
                      let liveProvider = snapshot.providers.first(where: { $0.id == provider.rawValue.lowercased() }),
                      liveProvider.activeAccountID == account.id
                else {
                    self.lastEvent = "\(provider.rawValue) 전환 후 readback 불일치 · 다시 확인하세요"
                    return
                }
                self.apply(snapshot: snapshot)
                self.lastEvent = "✓ \(provider.rawValue) / \(account.name) 전환 확인"
            }
        }
    }

    func launchGrok(grokHome: String) {
        let encodedHome = Data(grokHome.utf8).base64EncodedString()
        let command = "export GROK_HOME=\"$(printf %s '\(encodedHome)' | /usr/bin/base64 -D)\"; exec grok"
        let script = "tell application \"Terminal\" to do script \"\(command.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\""))\""
        lastEvent = "Grok 새 세션 여는 중…"
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let task = Process()
            task.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
            task.arguments = ["-e", script]
            task.standardOutput = Pipe()
            task.standardError = Pipe()
            do {
                try task.run()
                task.waitUntilExit()
                DispatchQueue.main.async {
                    self?.lastEvent = task.terminationStatus == 0
                        ? "✓ Grok 새 세션 명령을 Terminal에 전달했습니다"
                        : "Grok Terminal 실행 실패 · 상태를 확인하세요"
                }
            } catch {
                DispatchQueue.main.async {
                    self?.lastEvent = "Grok Terminal 실행 실패 · 상태를 확인하세요"
                }
            }
        }
    }

    private static let samples: [ProviderState] = [
        ProviderState(
            id: .claude,
            activeAccountID: "claude-personal",
            accounts: [
                Account(id: "claude-personal", name: "개인 Max", email: "sample@switchboard.demo", plan: "Max 5x", health: .ready, switchable: true, usage: [
                    UsageWindow(label: "5시간", usedPercent: 38, resetsIn: "2시간 14분"),
                    UsageWindow(label: "주간", usedPercent: 71, resetsIn: "3일 8시간")
                ]),
                Account(id: "claude-work", name: "팀", email: "team@switchboard.demo", plan: "Team", health: .ready, switchable: true, usage: [
                    UsageWindow(label: "5시간", usedPercent: 12, resetsIn: "4시간 2분"),
                    UsageWindow(label: "주간", usedPercent: 44, resetsIn: "5일 1시간")
                ])
            ],
            checkedAt: "방금",
            note: nil
        ),
        ProviderState(
            id: .codex,
            activeAccountID: "codex-work",
            accounts: [
                Account(id: "codex-personal", name: "개인 Plus", email: "sample@switchboard.demo", plan: "Plus", health: .ready, switchable: true, usage: [
                    UsageWindow(label: "5시간", usedPercent: 17, resetsIn: "1시간 2분"),
                    UsageWindow(label: "주간", usedPercent: 42, resetsIn: "48시간")
                ], benefits: [
                    BenefitBalance(label: "리셋 크레딧", amount: "2개", detail: "가장 빠른 만료 · 5일", isExpiringSoon: true)
                ]),
                Account(id: "codex-work", name: "팀 Pro", email: "team@switchboard.demo", plan: "Business Pro", health: .ready, switchable: true, usage: [
                    UsageWindow(label: "5시간", usedPercent: 64, resetsIn: "3시간 18분"),
                    UsageWindow(label: "주간", usedPercent: 81, resetsIn: "19시간")
                ], benefits: [
                    BenefitBalance(label: "리셋 크레딧", amount: "1개", detail: "14일 후 만료")
                ])
            ],
            checkedAt: "방금",
            note: nil
        ),
        ProviderState(
            id: .grok,
            activeAccountID: "grok-personal",
            accounts: [
                Account(id: "grok-personal", name: "개인", email: "sample@switchboard.demo", plan: "Subscriber", health: .ready, switchable: false, usage: [
                    UsageWindow(label: "주간", usedPercent: 54, resetsIn: "2일 6시간")
                ], benefits: [
                    BenefitBalance(label: "Extra Usage", amount: "$18.40", detail: "구매 후 1년 만료")
                ]),
                Account(id: "grok-api", name: "API Key", email: "console.x.ai", plan: "Usage based", health: .expiring, switchable: true, usage: [
                    UsageWindow(label: "월간", usedPercent: 23, resetsIn: "12일")
                ], benefits: [
                    BenefitBalance(label: "선불 크레딧", amount: "$42.80", detail: "팀 잔액")
                ])
            ],
            checkedAt: "1분 전",
            note: "브라우저 로그인과 API Key 상태를 구분"
        ),
        ProviderState(
            id: .gemini,
            activeAccountID: "gemini-enterprise",
            accounts: [
                Account(id: "gemini-enterprise", name: "팀 Code Assist", email: "team@switchboard.demo", plan: "Enterprise", health: .ready, switchable: false, usage: [
                    UsageWindow(label: "일간", usedPercent: 63, resetsIn: "9시간")
                ]),
                Account(id: "gemini-personal", name: "개인 Google", email: "sample@switchboard.demo", plan: "Individual", health: .unavailable, switchable: false, usage: []),
                Account(id: "gemini-api", name: "Gemini API", email: "AI Studio Key", plan: "Usage based", health: .ready, switchable: false, usage: [
                    UsageWindow(label: "일간", usedPercent: 31, resetsIn: "9시간")
                ])
            ],
            checkedAt: "2분 전",
            note: "개인 계정 지원 여부를 인증 방식별로 확인"
        )
    ]
}

private struct LiveSnapshot: Decodable {
    let providers: [LiveProvider]
}

private struct LiveProvider: Decodable {
    let id: String
    let activeAccountID: String
    let accounts: [LiveAccount]
    let checkedAt: String
    let note: String?
}

private struct SwitchResponse: Decodable {
    let ok: Bool
    let provider: String
    let requestedAccountID: String
    let activeAccountID: String?
    let restartRequired: Bool
    let message: String
}

private struct LiveAccount: Decodable {
    let id: String
    let name: String
    let email: String
    let plan: String
    let health: String
    let switchable: Bool
    let usage: [LiveUsage]
    let benefits: [LiveBenefit]
    let origin: String
    let grokHome: String?

    var isLiveOrigin: Bool {
        origin == "live"
    }

    var account: Account {
        Account(
            id: id,
            name: name,
            email: email,
            plan: plan,
            health: AuthHealth(rawValue: health == "ready" ? "정상" : health == "expiring" ? "갱신 필요" : "전환 불가") ?? .unavailable,
            switchable: switchable,
            usage: usage.map { UsageWindow(label: $0.label, usedPercent: $0.usedPercent, resetsIn: $0.resetsIn) },
            benefits: benefits.map { BenefitBalance(label: $0.label, amount: $0.amount, detail: $0.detail, isExpiringSoon: $0.isExpiringSoon) },
            origin: origin == "live" ? .live : .demo,
            grokHome: grokHome
        )
    }
}

private struct LiveUsage: Decodable {
    let label: String
    let usedPercent: Int
    let resetsIn: String
}

private struct LiveBenefit: Decodable {
    let label: String
    let amount: String
    let detail: String
    let isExpiringSoon: Bool
}

@main
struct SwitchboardPrototypeApp: App {
    @NSApplicationDelegateAdaptor(PrototypeAppDelegate.self) private var appDelegate
    @StateObject private var store = PrototypeStore()

    var body: some Scene {
        Window("Switchboard", id: "preview") {
            RootView(store: store)
        }
        .defaultSize(width: 440, height: 610)

        MenuBarExtra {
            RootView(store: store)
        } label: {
            Label("Switchboard", systemImage: "square.grid.2x2.fill")
        }
        .menuBarExtraStyle(.window)
    }
}

@MainActor
final class PrototypeAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        guard !CommandLine.arguments.contains("--preview") else { return }
        DispatchQueue.main.async {
            NSApplication.shared.windows
                .filter { $0.title == "Switchboard" }
                .forEach { $0.close() }
        }
    }
}

struct RootView: View {
    @ObservedObject var store: PrototypeStore

    var body: some View {
        VStack(spacing: 0) {
            HeaderView(store: store)

            FocusVariant(store: store)
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            Divider()
            HStack(spacing: 10) {
                Circle()
                    .fill(store.lastEvent.hasPrefix("✓") ? Color.green : Color.secondary)
                    .frame(width: 6, height: 6)
                Text(store.lastEvent)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Spacer()
                Button("종료") { NSApplication.shared.terminate(nil) }
                    .buttonStyle(.plain)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 14)
            .frame(height: 34)

        }
        .frame(width: 440, height: 610)
        .background(Color(nsColor: .windowBackgroundColor))
    }
}

struct HeaderView: View {
    @ObservedObject var store: PrototypeStore

    var body: some View {
        HStack {
            BrandIcon()
            VStack(alignment: .leading, spacing: 2) {
                Text("Switchboard")
                    .font(.headline)
                Text("AI Account Switcher")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text(store.dataMode)
                .font(.caption2.bold())
                .foregroundStyle(store.dataMode == "LIVE" ? Color.green : Color.orange)
            Button {
                store.refreshLiveData()
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .buttonStyle(.plain)
            .help("실데이터 다시 읽기")
            Image(systemName: "lock.shield.fill")
                .foregroundStyle(.green)
                .help("토큰은 UI·스냅샷에 노출하거나 저장하지 않습니다")
        }
        .padding(14)
    }
}

struct BrandIcon: View {
    private var image: NSImage? {
        guard let url = Bundle.main.url(forResource: "SwitchboardIcon-1024", withExtension: "png") else {
            return nil
        }
        return NSImage(contentsOf: url)
    }

    var body: some View {
        Group {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
            } else {
                Image(systemName: "square.grid.2x2.fill")
                    .resizable()
                    .scaledToFit()
                    .padding(7)
                    .foregroundStyle(.blue)
            }
        }
        .frame(width: 36, height: 36)
        .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
        .shadow(color: .black.opacity(0.18), radius: 3, y: 1)
    }
}

struct OverviewVariant: View {
    @ObservedObject var store: PrototypeStore
    let onOpen: (ProviderID) -> Void

    var body: some View {
        ScrollView {
            LazyVStack(spacing: 10) {
                ForEach(store.providers) { provider in
                    ProviderCard(
                        provider: provider,
                        onOpen: { onOpen(provider.id) },
                        onSwitch: { accountID in
                            store.switchAccount(provider: provider.id, accountID: accountID)
                        }
                    )
                }
            }
            .padding(.horizontal, 12)
            .padding(.bottom, 12)
        }
    }
}

struct ProviderCard: View {
    let provider: ProviderState
    let onOpen: () -> Void
    let onSwitch: (String) -> Void
    @State private var isHovering = false

    var body: some View {
        VStack(spacing: 9) {
            VStack(spacing: 9) {
                HStack {
                    ProviderMark(id: provider.id)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(provider.id.rawValue).font(.subheadline.bold())
                        Text(provider.activeAccount?.name ?? "미연결")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    if let usage = provider.usage.max(by: { $0.usedPercent < $1.usedPercent }) {
                        UsageRing(percent: usage.usedPercent, color: provider.id.tint)
                    }
                }

                ForEach(provider.usage, id: \.label) { usage in
                    UsageLine(window: usage, tint: provider.id.tint)
                }
            }
            .contentShape(Rectangle())
            .onTapGesture(perform: onOpen)

            if provider.accounts.count >= 2 {
                HStack(spacing: 6) {
                    ForEach(provider.accounts) { account in
                        Button {
                            onSwitch(account.id)
                        } label: {
                            HStack(spacing: 4) {
                                if account.id == provider.activeAccountID {
                                    Image(systemName: "checkmark.circle.fill")
                                }
                                Text(account.name)
                            }
                            .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                        .disabled(!account.switchable)
                    }
                }
            }
        }
        .padding(11)
        .background {
            if isHovering {
                RoundedRectangle(cornerRadius: 12)
                    .fill(provider.id.tint.opacity(0.10))
            } else {
                RoundedRectangle(cornerRadius: 12)
                    .fill(.quaternary.opacity(0.45))
            }
        }
        .onHover { isHovering = $0 }
    }
}

struct FocusVariant: View {
    @ObservedObject var store: PrototypeStore
    @State private var showsOverview = false

    var body: some View {
        HStack(spacing: 0) {
            VStack(spacing: 4) {
                Button {
                    showsOverview = true
                } label: {
                    VStack(spacing: 5) {
                        Image(systemName: "square.grid.2x2.fill")
                            .font(.caption.bold())
                            .foregroundStyle(.secondary)
                            .frame(width: 25, height: 25)
                            .background(.secondary.opacity(0.10), in: RoundedRectangle(cornerRadius: 7))
                        Text("전체").font(.caption2)
                    }
                    .frame(width: 66, height: 58)
                    .background(
                        showsOverview ? Color.secondary.opacity(0.12) : Color.clear,
                        in: RoundedRectangle(cornerRadius: 10)
                    )
                }
                .buttonStyle(.plain)

                ForEach(ProviderID.allCases) { id in
                    Button {
                        showsOverview = false
                        store.selectedProvider = id
                    } label: {
                        VStack(spacing: 5) {
                            ProviderMark(id: id, compact: true)
                            Text(id.rawValue).font(.caption2)
                        }
                        .frame(width: 66, height: 58)
                        .background(
                            !showsOverview && id == store.selectedProvider ? id.tint.opacity(0.14) : Color.clear,
                            in: RoundedRectangle(cornerRadius: 10)
                        )
                    }
                    .buttonStyle(.plain)
                }
                Spacer()
            }
            .padding(10)
            .background(.quaternary.opacity(0.35))

            Divider()

            if showsOverview {
                VStack(alignment: .leading, spacing: 8) {
                    Text("전체 현황")
                        .font(.title3.bold())
                        .padding(.horizontal, 14)
                        .padding(.top, 14)
                    OverviewVariant(store: store) { providerID in
                        store.selectedProvider = providerID
                        showsOverview = false
                    }
                }
            } else {
                ProviderDetail(
                    provider: store.provider(store.selectedProvider),
                    onSwitch: { store.switchAccount(provider: store.selectedProvider, accountID: $0) },
                    onLaunchGrok: { store.launchGrok(grokHome: $0) }
                )
                .padding(14)
            }
        }
    }
}

struct ProviderDetail: View {
    let provider: ProviderState
    let onSwitch: (String) -> Void
    let onLaunchGrok: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                ProviderMark(id: provider.id)
                VStack(alignment: .leading) {
                    Text(provider.id.rawValue).font(.title3.bold())
                    Text("마지막 확인 · \(provider.checkedAt)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Text("\(provider.highestUsage)%")
                    .font(.title2.monospacedDigit().bold())
            }

            VStack(spacing: 10) {
                ForEach(Array(quotaSlots(for: provider.usage).enumerated()), id: \.offset) { _, usage in
                    if let usage {
                        UsageLine(window: usage, tint: provider.id.tint)
                    } else {
                        UnavailableUsageLine()
                    }
                }
            }

            if let recommended = provider.recommendedAccount {
                RecommendationBanner(
                    account: recommended,
                    tint: provider.id.tint,
                    isActive: recommended.id == provider.activeAccountID,
                    action: { onSwitch(recommended.id) }
                )
            } else {
                Label(provider.recommendationHoldReason, systemImage: "questionmark.circle")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(9)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.quaternary.opacity(0.32), in: RoundedRectangle(cornerRadius: 8))
            }

            if provider.id == .grok {
                VStack(alignment: .leading, spacing: 4) {
                    Link("Grok 웹에서 재설정 상태 확인/적용", destination: URL(string: "https://grok.com/?referrer=website#settings/usage")!)
                        .font(.caption)
                    Text("재설정 횟수와 만료일은 로컬 공식 API가 확인되기 전까지 표시하지 않습니다.")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(9)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.quaternary.opacity(0.32), in: RoundedRectangle(cornerRadius: 8))
            }

            if provider.id == .gemini {
                HStack(alignment: .top, spacing: 7) {
                    Image(systemName: "person.crop.circle.badge.exclamationmark")
                        .foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("계정 전환 미지원")
                            .font(.caption.weight(.semibold))
                        Text("AGY/Gemini는 즉시 전환을 지원하지 않습니다. 사용량을 새로고침하거나 CLI에서 재인증하세요.")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .layoutPriority(1)
                }
                    .padding(8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 8))
            }

            Text("계정")
                .font(.caption.bold())
                .foregroundStyle(.secondary)

            ScrollView {
                LazyVStack(spacing: 5) {
                    ForEach(provider.accounts) { account in
                        AccountRow(
                            provider: provider.id,
                            account: account,
                            isActive: account.id == provider.activeAccountID,
                            isRecommended: account.id == provider.recommendedAccount?.id,
                            showsUsage: true,
                            action: { onSwitch(account.id) },
                            onLaunchGrok: { home in onLaunchGrok(home) }
                        )
                    }
                }
            }
            .frame(maxHeight: 260)

            Label(
                provider.note ?? "활성 계정의 공식 상태를 마지막 확인 시각 기준으로 표시",
                systemImage: "info.circle"
            )
            .font(.caption)
            .foregroundStyle(.secondary)
            .lineLimit(2)
            .padding(10)
            .frame(maxWidth: .infinity, minHeight: 48, alignment: .leading)
            .background(.quaternary.opacity(0.4), in: RoundedRectangle(cornerRadius: 8))
        }
    }
}

struct AccountRow: View {
    let provider: ProviderID
    let account: Account
    let isActive: Bool
    var isRecommended = false
    var showsUsage = false
    let action: () -> Void
    var onLaunchGrok: ((String) -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 10) {
                ProviderMark(id: provider, compact: true)
                VStack(alignment: .leading, spacing: 3) {
                    Text(account.name)
                        .font(.subheadline.weight(.medium))
                        .lineLimit(1)
                        .truncationMode(.tail)
                        .layoutPriority(2)
                    HStack(spacing: 5) {
                        AccountBadge(text: account.plan, color: .secondary)
                        AccountBadge(text: account.origin.rawValue, color: account.origin.color)
                        if isRecommended {
                            AccountBadge(text: "추천", color: .green)
                        }
                    }
                    Text(account.email)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                        .layoutPriority(1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                HStack(spacing: 4) {
                    Circle().fill(account.health.color).frame(width: 7, height: 7)
                    Text(account.health.rawValue)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    if isActive {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundStyle(.green)
                    } else if account.switchable {
                        Button(action: action) {
                            Image(systemName: "arrow.right.circle")
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(provider.tint)
                        .help("이 계정으로 전환")
                    } else {
                        Image(systemName: "arrow.right.circle")
                            .foregroundStyle(.secondary)
                    }
                }
                .fixedSize(horizontal: true, vertical: false)
                .padding(.top, 2)
            }

            if showsUsage {
                HStack(spacing: 6) {
                    ForEach(Array(quotaSlots(for: account.usage).enumerated()), id: \.offset) { _, window in
                        QuotaChip(window: window)
                    }
                }
                .padding(.leading, 35)

                HStack(spacing: 5) {
                    Image(systemName: "ticket")
                    if let benefit = account.benefits.first {
                        Text("\(benefit.label) \(benefit.amount)")
                            .fontWeight(.medium)
                        Text("· \(benefit.detail)")
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    } else {
                        Text("추가 크레딧 없음")
                            .foregroundStyle(.secondary)
                    }
                }
                .font(.caption2)
                .padding(.leading, 35)
            }

            if provider == .grok, let grokHome = account.grokHome, let onLaunchGrok {
                VStack(alignment: .leading, spacing: 4) {
                    Button("새 Grok 세션 열기") {
                        onLaunchGrok(grokHome)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    Text("기존 세션은 바꾸지 않고 이 프로필의 GROK_HOME으로 새 세션을 시작합니다.")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.leading, 35)
            }
        }
        .padding(9)
        .background(
            isActive ? provider.tint.opacity(0.12) : Color.clear,
            in: RoundedRectangle(cornerRadius: 9)
        )
    }
}

struct AccountBadge: View {
    let text: String
    let color: Color

    var body: some View {
        Text(text)
            .font(.caption2.bold())
            .foregroundStyle(color)
            .lineLimit(1)
            .truncationMode(.tail)
    }
}

struct QuotaChip: View {
    let window: UsageWindow?

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            if let window {
                Text("\(window.label) · \(window.usedPercent)% 사용")
                    .font(.caption2.monospacedDigit().weight(.medium))
                    .foregroundStyle(window.usedPercent >= 85 ? Color.red : Color.primary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                Text("\(100 - window.usedPercent)% 남음 · \(window.resetsIn) 후")
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.66)
            } else {
                Text("추가 한도 · 미제공")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                Text("공급자 응답 없음")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
            }
        }
        .padding(.horizontal, 7)
        .padding(.vertical, 5)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.35), in: RoundedRectangle(cornerRadius: 6))
    }
}

struct RecommendationBanner: View {
    let account: Account
    let tint: Color
    let isActive: Bool
    let action: () -> Void

    var body: some View {
        HStack(spacing: 9) {
            Image(systemName: "wand.and.stars")
                .foregroundStyle(tint)
            VStack(alignment: .leading, spacing: 2) {
                Text("추천 · \(account.name)")
                    .font(.caption.bold())
                    .lineLimit(1)
                Text(account.recommendationReason.replacingOccurrences(of: " / ", with: "\n"))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .layoutPriority(1)
            Button(isActive ? "사용 중" : account.switchable ? "전환" : "전환 미연결", action: action)
                .buttonStyle(.bordered)
                .controlSize(.small)
                .disabled(isActive || !account.switchable)
                .fixedSize(horizontal: true, vertical: false)
        }
        .padding(9)
        .background(tint.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
    }
}

struct UnavailableUsageLine: View {
    var body: some View {
        VStack(spacing: 4) {
            HStack {
                Text("추가 한도")
                    .font(.caption)
                Spacer()
                Text("공급자 미제공")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            ProgressView(value: 0, total: 100)
                .tint(.secondary.opacity(0.35))
        }
        .accessibilityLabel("추가 한도 공급자 미제공")
    }
}

struct ProviderMark: View {
    let id: ProviderID
    var compact = false

    var body: some View {
        if let brandIcon = Self.brandIcon(for: id) {
            Image(nsImage: brandIcon)
                .resizable()
                .interpolation(.high)
                .aspectRatio(contentMode: .fit)
                .frame(width: compact ? 25 : 31, height: compact ? 25 : 31)
                .accessibilityHidden(true)
        } else {
            Image(systemName: id.icon)
                .font(compact ? .caption.bold() : .body.bold())
                .foregroundStyle(id.tint)
                .frame(width: compact ? 25 : 31, height: compact ? 25 : 31)
                .background(id.tint.opacity(0.13), in: RoundedRectangle(cornerRadius: compact ? 7 : 9))
                .accessibilityHidden(true)
        }
    }

    private static func brandIcon(for provider: ProviderID) -> NSImage? {
        guard let url = Bundle.main.url(
            forResource: provider.appIconResourceName,
            withExtension: provider.appIconResourceExtension
        ) else {
            return nil
        }
        return NSImage(contentsOf: url)
    }
}

struct UsageRing: View {
    let percent: Int
    let color: Color

    var body: some View {
        ZStack {
            Circle().stroke(color.opacity(0.16), lineWidth: 4)
            Circle()
                .trim(from: 0, to: CGFloat(percent) / 100)
                .stroke(color, style: StrokeStyle(lineWidth: 4, lineCap: .round))
                .rotationEffect(.degrees(-90))
            Text("\(percent)")
                .font(.caption2.monospacedDigit().bold())
        }
        .frame(width: 39, height: 39)
    }
}

struct UsageLine: View {
    let window: UsageWindow
    let tint: Color

    var body: some View {
        VStack(spacing: 4) {
            HStack {
                Text(window.label).font(.caption)
                Spacer()
                Text("\(window.usedPercent)% 사용")
                    .font(.caption.monospacedDigit().bold())
                Text("· \(window.resetsIn) 후")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            ProgressView(value: Double(window.usedPercent), total: 100)
                .tint(window.usedPercent >= 85 ? .red : tint)
        }
    }
}
