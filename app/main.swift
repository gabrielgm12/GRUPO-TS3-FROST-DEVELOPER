import Cocoa
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    let url = URL(string: "http://127.0.0.1:8765")!

    func applicationDidFinishLaunching(_ n: Notification) {
        startServer()

        web = WKWebView(frame: .zero)
        web.setValue(false, forKey: "drawsBackground")
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1080, height: 720),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Grupos TS3"
        window.isMovableByWindowBackground = true
        window.minSize = NSSize(width: 760, height: 520)
        window.backgroundColor = NSColor(red: 0.06, green: 0.07, blue: 0.09, alpha: 1)
        window.appearance = NSAppearance(named: .darkAqua)
        window.contentView = web
        window.center()
        window.delegate = self
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        load(tries: 0)
    }

    func startServer() {
        guard let res = Bundle.main.resourcePath else { return }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        p.arguments = [res + "/server.py"]
        var env = ProcessInfo.processInfo.environment
        let data = NSHomeDirectory() + "/Library/Application Support/GruposTS3"
        env["GRUPOS_DATA"] = data
        env["GRUPOS_NO_BROWSER"] = "1"
        p.environment = env
        p.currentDirectoryURL = URL(fileURLWithPath: res)
        try? p.run()
        server = p
    }

    func load(tries: Int) {
        var req = URLRequest(url: url)
        req.timeoutInterval = 1
        URLSession.shared.dataTask(with: req) { _, resp, _ in
            DispatchQueue.main.async {
                if resp != nil { self.web.load(URLRequest(url: self.url)) }
                else if tries < 30 { DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self.load(tries: tries + 1) } }
                else { self.web.loadHTMLString("<body style='background:#0f1115;color:#fff;font:16px system-ui;padding:40px'>Não consegui iniciar o servidor local.</body>", baseURL: nil) }
            }
        }.resume()
    }

    func windowWillClose(_ n: Notification) { NSApp.terminate(nil) }
    func applicationWillTerminate(_ n: Notification) { server?.terminate() }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)

let menu = NSMenu()
let appItem = NSMenuItem(); menu.addItem(appItem)
let sub = NSMenu(); appItem.submenu = sub
sub.addItem(withTitle: "Sair", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
let editItem = NSMenuItem(); menu.addItem(editItem)
let edit = NSMenu(title: "Editar"); editItem.submenu = edit
edit.addItem(withTitle: "Copiar", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
edit.addItem(withTitle: "Colar", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
edit.addItem(withTitle: "Selecionar tudo", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
app.mainMenu = menu
app.run()
