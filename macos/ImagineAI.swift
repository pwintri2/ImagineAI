import Cocoa
import UniformTypeIdentifiers
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var serverTask: Process?

    let url = URL(string: "http://127.0.0.1:8799/?edition=macos")!
    let logPath = (NSHomeDirectory() as NSString).appendingPathComponent("Library/Logs/ImagineAI-wrapper.log")

    var repoPath: String {
        if let value = ProcessInfo.processInfo.environment["IMAGINEAI_REPO_PATH"], !value.isEmpty {
            return value
        }
        if let value = Bundle.main.object(forInfoDictionaryKey: "ImagineAIRepoPath") as? String, !value.isEmpty {
            return value
        }
        return FileManager.default.currentDirectoryPath
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        startServerIfNeeded()
        createWindow()
        waitForServerAndLoad()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
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
        completionHandler(downloadDestination(for: filename))
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        showDownloadError(error.localizedDescription)
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

    func showDownloadError(_ message: String) {
        DispatchQueue.main.async {
            let alert = NSAlert()
            alert.alertStyle = .warning
            alert.messageText = "Download niet opgeslagen"
            alert.informativeText = message
            alert.beginSheetModal(for: self.window)
        }
    }

    func startServerIfNeeded() {
        if isPortOpen(8799) { return }

        let serverPath = URL(fileURLWithPath: repoPath).appendingPathComponent("server.py")
        guard FileManager.default.fileExists(atPath: serverPath.path) else {
            showErrorAndQuit("server.py niet gevonden in \(repoPath). Installeer de app opnieuw vanuit de ImagineAI-repository.")
            return
        }

        let task = Process()
        task.currentDirectoryURL = URL(fileURLWithPath: repoPath)
        task.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        task.arguments = ["-u", "server.py", "--host", "127.0.0.1", "--port", "8799"]
        task.environment = mergedEnvironment([
            "COMFYUI_URL": "http://127.0.0.1:8188",
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
                    DispatchQueue.main.async {
                        self.webView.load(URLRequest(url: self.url))
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
