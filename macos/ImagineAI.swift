import Cocoa
import UniformTypeIdentifiers
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    struct PendingDownloadReplacement {
        let temporaryURL: URL
        let destinationURL: URL
    }

    var window: NSWindow!
    var webView: WKWebView!
    var serverTask: Process?
    var comfyTask: Process?
    var comfyMonitor: Timer?
    var lastComfyStartAttempt = Date.distantPast
    var pendingDownloadReplacements: [ObjectIdentifier: PendingDownloadReplacement] = [:]

    let url = URL(string: "http://127.0.0.1:8799/?edition=macos")!
    let logPath = (NSHomeDirectory() as NSString).appendingPathComponent("Library/Logs/ImagineAI-wrapper.log")
    let comfyLogPath = (NSHomeDirectory() as NSString).appendingPathComponent("Library/Logs/ImagineAI-comfyui.log")
    let comfyPort: Int32 = 8188

    var repoPath: String {
        if let value = ProcessInfo.processInfo.environment["IMAGINEAI_REPO_PATH"], !value.isEmpty {
            return value
        }
        if let value = Bundle.main.object(forInfoDictionaryKey: "ImagineAIRepoPath") as? String, !value.isEmpty {
            return value
        }
        return FileManager.default.currentDirectoryPath
    }

    var comfyPath: String {
        if let value = ProcessInfo.processInfo.environment["IMAGINEAI_COMFYUI_PATH"], !value.isEmpty {
            return (value as NSString).expandingTildeInPath
        }
        if let value = Bundle.main.object(forInfoDictionaryKey: "ComfyUIPath") as? String, !value.isEmpty {
            return (value as NSString).expandingTildeInPath
        }
        return ("~/ComfyUI" as NSString).expandingTildeInPath
    }

    var comfyPythonPath: String {
        if let value = ProcessInfo.processInfo.environment["COMFY_PYTHON"], !value.isEmpty {
            return (value as NSString).expandingTildeInPath
        }
        if let value = ProcessInfo.processInfo.environment["COMFYUI_PYTHON"], !value.isEmpty {
            return (value as NSString).expandingTildeInPath
        }
        return URL(fileURLWithPath: comfyPath).appendingPathComponent(".venv/bin/python").path
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        startComfyUIIfNeeded()
        startServerIfNeeded()
        createWindow()
        startComfyMonitor()
        waitForServerAndLoad()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        comfyMonitor?.invalidate()
        if let task = serverTask, task.isRunning {
            task.terminate()
        }
    }

    func createWindow() {
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.loadHTMLString("""
            <!doctype html><html lang="nl"><meta charset="utf-8">
            <style>body{background:#0b0612;color:#f1f5f9;font:16px system-ui;display:grid;
            place-content:center;min-height:90vh;text-align:center}p{color:#94a3b8}</style>
            <h1>ImagineAI wordt gestart</h1><p>De lokale studio wordt geladen…</p></html>
            """, baseURL: nil)

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1280, height: 900),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.center()
        window.title = "ImagineAI for Mac"
        window.minSize = NSSize(width: 900, height: 650)
        window.contentView = webView
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func webView(
        _ webView: WKWebView,
        runOpenPanelWith parameters: WKOpenPanelParameters,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping ([URL]?) -> Void
    ) {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.image]
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseFiles = true
        panel.canChooseDirectories = parameters.allowsDirectories

        panel.beginSheetModal(for: window) { response in
            completionHandler(response == .OK ? panel.urls : nil)
        }
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        preferences: WKWebpagePreferences,
        decisionHandler: @escaping (WKNavigationActionPolicy, WKWebpagePreferences) -> Void
    ) {
        if navigationAction.shouldPerformDownload {
            decisionHandler(.download, preferences)
            return
        }
        decisionHandler(.allow, preferences)
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationResponse: WKNavigationResponse,
        decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void
    ) {
        if isAttachmentResponse(navigationResponse.response) {
            decisionHandler(.download)
            return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }

    func download(
        _ download: WKDownload,
        decideDestinationUsing response: URLResponse,
        suggestedFilename: String,
        completionHandler: @escaping (URL?) -> Void
    ) {
        let filename = cleanDownloadFilename(suggestedFilename)
        let contentType = downloadContentType(for: response, filename: filename)
        guard contentType == .mpeg4Movie else {
            completionHandler(downloadDestination(for: filename))
            return
        }

        let panel = NSSavePanel()
        panel.title = "Bewaar video als MP4"
        panel.prompt = "Bewaar"
        panel.nameFieldStringValue = filename
        panel.canCreateDirectories = true
        panel.isExtensionHidden = false
        panel.allowedContentTypes = [.mpeg4Movie]

        panel.beginSheetModal(for: window) { panelResponse in
            guard panelResponse == .OK, let destinationURL = panel.url else {
                completionHandler(nil)
                return
            }

            do {
                let downloadURL = try self.prepareDownloadDestination(
                    for: download,
                    destinationURL: destinationURL
                )
                completionHandler(downloadURL)
            } catch {
                completionHandler(nil)
                self.showDownloadError(error.localizedDescription)
            }
        }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        cleanUpPendingReplacement(for: download)
        let nsError = error as NSError
        if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled {
            return
        }
        showDownloadError(error.localizedDescription)
    }

    func downloadDidFinish(_ download: WKDownload) {
        let key = ObjectIdentifier(download)
        guard let replacement = pendingDownloadReplacements.removeValue(forKey: key) else {
            return
        }

        do {
            if FileManager.default.fileExists(atPath: replacement.destinationURL.path) {
                _ = try FileManager.default.replaceItemAt(
                    replacement.destinationURL,
                    withItemAt: replacement.temporaryURL
                )
            } else {
                try FileManager.default.moveItem(
                    at: replacement.temporaryURL,
                    to: replacement.destinationURL
                )
            }
        } catch {
            try? FileManager.default.removeItem(at: replacement.temporaryURL)
            showDownloadError("Het gedownloade bestand kon niet op de gekozen locatie worden geplaatst.\n\n\(error.localizedDescription)")
        }
    }

    func isAttachmentResponse(_ response: URLResponse) -> Bool {
        guard
            let http = response as? HTTPURLResponse,
            let disposition = http.value(forHTTPHeaderField: "Content-Disposition")
        else {
            return false
        }
        return disposition.localizedCaseInsensitiveContains("attachment")
    }

    func cleanDownloadFilename(_ value: String) -> String {
        let cleaned = value
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "\\", with: "_")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return cleaned.isEmpty ? "imagineai-video.mp4" : cleaned
    }

    func downloadContentType(for response: URLResponse, filename: String) -> UTType? {
        let ext = (filename as NSString).pathExtension.lowercased()
        let mimeType = response.mimeType?.lowercased()
        if ext == "mp4" || mimeType == "video/mp4" || mimeType == "application/mp4" {
            return .mpeg4Movie
        }
        if let mimeType, let type = UTType(mimeType: mimeType) {
            return type
        }
        return ext.isEmpty ? nil : UTType(filenameExtension: ext)
    }

    func downloadDestination(for filename: String) -> URL {
        let downloads = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Downloads", isDirectory: true)
        try? FileManager.default.createDirectory(at: downloads, withIntermediateDirectories: true)

        let base = (filename as NSString).deletingPathExtension
        let ext = (filename as NSString).pathExtension
        var candidate = downloads.appendingPathComponent(filename)
        var index = 2
        while FileManager.default.fileExists(atPath: candidate.path) {
            let suffix = ext.isEmpty ? "" : ".\(ext)"
            candidate = downloads.appendingPathComponent("\(base) \(index)\(suffix)")
            index += 1
        }
        return candidate
    }

    func prepareDownloadDestination(for download: WKDownload, destinationURL: URL) throws -> URL {
        let key = ObjectIdentifier(download)
        pendingDownloadReplacements.removeValue(forKey: key)
        guard FileManager.default.fileExists(atPath: destinationURL.path) else {
            return destinationURL
        }

        let temporaryURL = destinationURL.deletingLastPathComponent()
            .appendingPathComponent(".ImagineAI-\(UUID().uuidString).download")
        pendingDownloadReplacements[key] = PendingDownloadReplacement(
            temporaryURL: temporaryURL,
            destinationURL: destinationURL
        )
        return temporaryURL
    }

    func cleanUpPendingReplacement(for download: WKDownload) {
        let key = ObjectIdentifier(download)
        guard let replacement = pendingDownloadReplacements.removeValue(forKey: key) else {
            return
        }
        try? FileManager.default.removeItem(at: replacement.temporaryURL)
    }

    func showDownloadError(_ message: String) {
        DispatchQueue.main.async {
            let alert = NSAlert()
            alert.alertStyle = .warning
            alert.messageText = "Download niet opgeslagen"
            alert.informativeText = message
            alert.beginSheetModal(for: self.window)
        }
    }

    func startComfyMonitor() {
        comfyMonitor?.invalidate()
        comfyMonitor = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            self?.startComfyUIIfNeeded()
        }
    }

    func startComfyUIIfNeeded() {
        if isPortOpen(comfyPort) { return }
        if let task = comfyTask, task.isRunning { return }
        guard Date().timeIntervalSince(lastComfyStartAttempt) >= 10 else { return }
        lastComfyStartAttempt = Date()

        let comfyURL = URL(fileURLWithPath: comfyPath, isDirectory: true)
        let mainPath = comfyURL.appendingPathComponent("main.py").path
        guard FileManager.default.fileExists(atPath: mainPath) else {
            appendLog("ComfyUI niet gevonden in \(comfyPath).", to: comfyLogPath)
            return
        }
        guard FileManager.default.isExecutableFile(atPath: comfyPythonPath) else {
            appendLog("ComfyUI Python is niet uitvoerbaar: \(comfyPythonPath)", to: comfyLogPath)
            return
        }

        let task = Process()
        task.currentDirectoryURL = comfyURL
        task.executableURL = URL(fileURLWithPath: comfyPythonPath)
        task.arguments = ["-u", "main.py", "--listen", "127.0.0.1", "--port", String(comfyPort)]
        task.environment = mergedEnvironment(["PYTORCH_ENABLE_MPS_FALLBACK": "1"])
        task.standardInput = FileHandle.nullDevice

        FileManager.default.createFile(atPath: comfyLogPath, contents: nil)
        if let handle = FileHandle(forWritingAtPath: comfyLogPath) {
            task.standardOutput = handle
            task.standardError = handle
        }

        do {
            try task.run()
            comfyTask = task
        } catch {
            appendLog("Kon ComfyUI niet starten: \(error.localizedDescription)", to: comfyLogPath)
        }
    }

    func findServerPython() -> String? {
        let candidates = [
            ProcessInfo.processInfo.environment["IMAGINEAI_PYTHON"],
            Bundle.main.object(forInfoDictionaryKey: "ImagineAIPythonPath") as? String,
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            comfyPythonPath,
            "/Library/Developer/CommandLineTools/usr/bin/python3",
            "/usr/bin/python3"
        ].compactMap { $0 }.filter { !$0.isEmpty }

        for candidate in candidates {
            let path = (candidate as NSString).expandingTildeInPath
            guard FileManager.default.isExecutableFile(atPath: path) else { continue }
            let probe = Process()
            probe.executableURL = URL(fileURLWithPath: path)
            probe.arguments = ["-c", "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"]
            probe.standardOutput = FileHandle.nullDevice
            probe.standardError = FileHandle.nullDevice
            do {
                try probe.run()
                probe.waitUntilExit()
                if probe.terminationStatus == 0 { return path }
            } catch {
                continue
            }
        }
        return nil
    }

    func startServerIfNeeded() {
        if isPortOpen(8799) { return }

        let serverPath = URL(fileURLWithPath: repoPath).appendingPathComponent("server.py")
        guard FileManager.default.fileExists(atPath: serverPath.path) else {
            showErrorAndQuit("server.py niet gevonden in \(repoPath). Installeer de app opnieuw vanuit de ImagineAI-repository.")
            return
        }

        guard let pythonPath = findServerPython() else {
            showErrorAndQuit("Geen werkende Python 3.9 of nieuwer gevonden. Installeer Python of stel IMAGINEAI_PYTHON in op een werkende Python-installatie.")
            return
        }

        let task = Process()
        task.currentDirectoryURL = URL(fileURLWithPath: repoPath)
        task.executableURL = URL(fileURLWithPath: pythonPath)
        task.arguments = ["-u", "server.py", "--host", "127.0.0.1", "--port", "8799"]
        task.environment = mergedEnvironment([
            "COMFYUI_URL": "http://127.0.0.1:8188",
            "COMFY_PYTHON": comfyPythonPath,
            "COMFYUI_INPUT_DIR": URL(fileURLWithPath: comfyPath, isDirectory: true)
                .appendingPathComponent("input", isDirectory: true).path,
            "IMAGINEAI_PORT": "8799"
        ])

        FileManager.default.createFile(atPath: logPath, contents: nil)
        if let handle = FileHandle(forWritingAtPath: logPath) {
            task.standardOutput = handle
            task.standardError = handle
        }

        do {
            try task.run()
            serverTask = task
        } catch {
            showErrorAndQuit("Kon ImagineAI-server niet starten.\n\n\(error.localizedDescription)")
        }
    }

    func waitForServerAndLoad() {
        DispatchQueue.global(qos: .userInitiated).async {
            let deadline = Date().addingTimeInterval(20)
            while Date() < deadline {
                if self.isPortOpen(8799) {
                    if let task = self.comfyTask, task.isRunning {
                        let comfyDeadline = Date().addingTimeInterval(20)
                        while Date() < comfyDeadline && !self.isPortOpen(self.comfyPort) {
                            Thread.sleep(forTimeInterval: 0.25)
                        }
                    }
                    DispatchQueue.main.async {
                        self.webView.load(URLRequest(url: self.url))
                    }
                    return
                }
                if let task = self.serverTask, !task.isRunning {
                    DispatchQueue.main.async {
                        self.showErrorAndQuit("De ImagineAI-server is gestopt tijdens het opstarten (code \(task.terminationStatus)).\n\nControleer log: \(self.logPath)")
                    }
                    return
                }
                Thread.sleep(forTimeInterval: 0.25)
            }
            DispatchQueue.main.async {
                self.showErrorAndQuit("ImagineAI reageert niet op http://127.0.0.1:8799\n\nControleer log: \(self.logPath)")
            }
        }
    }

    func isPortOpen(_ port: Int32) -> Bool {
        let sock = socket(AF_INET, SOCK_STREAM, 0)
        if sock < 0 { return false }
        defer { close(sock) }

        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = in_port_t(UInt16(port).bigEndian)
        addr.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))

        return withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(sock, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) == 0
            }
        }
    }

    func mergedEnvironment(_ extra: [String: String]) -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        for (key, value) in extra { env[key] = value }
        return env
    }

    func appendLog(_ message: String, to path: String) {
        let line = "[\(ISO8601DateFormatter().string(from: Date()))] \(message)\n"
        guard let data = line.data(using: .utf8) else { return }
        if !FileManager.default.fileExists(atPath: path) {
            FileManager.default.createFile(atPath: path, contents: nil)
        }
        guard let handle = FileHandle(forWritingAtPath: path) else { return }
        handle.seekToEndOfFile()
        handle.write(data)
        try? handle.close()
    }

    func showErrorAndQuit(_ message: String) {
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = "ImagineAI for Mac"
        alert.informativeText = message
        alert.runModal()
        NSApp.terminate(nil)
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.setActivationPolicy(.regular)
app.delegate = delegate
app.run()
