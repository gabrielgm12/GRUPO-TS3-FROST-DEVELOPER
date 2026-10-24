import Cocoa
// Gera icon_1024.png a partir do banner: recorte quadrado em volta do "FROST" + cantos arredondados do macOS
let src = NSImage(contentsOfFile: "skin-frost.jpg")!
let cg = src.cgImage(forProposedRect: nil, context: nil, hints: nil)!
let side = 1140.0
let crop = CGRect(x: 400, y: 0, width: side, height: side)
let part = cg.cropping(to: crop)!

let S = 1024, pad = 100                      // margem padrão dos ícones do macOS
let inner = CGFloat(S - 2*pad)
let ctx = CGContext(data: nil, width: S, height: S, bitsPerComponent: 8, bytesPerRow: 0,
                    space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
let rect = CGRect(x: pad, y: pad, width: Int(inner), height: Int(inner))
let path = CGPath(roundedRect: rect, cornerWidth: inner*0.225, cornerHeight: inner*0.225, transform: nil)

ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -14), blur: 28, color: CGColor(gray: 0, alpha: 0.5))
ctx.addPath(path); ctx.setFillColor(CGColor(red: 0.02, green: 0.01, blue: 0.05, alpha: 1)); ctx.fillPath()
ctx.restoreGState()

ctx.saveGState()
ctx.addPath(path); ctx.clip()
ctx.draw(part, in: rect)
// leve vinheta roxa nas bordas
let grad = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
    colors: [CGColor(red: 0.55, green: 0.36, blue: 0.96, alpha: 0), CGColor(red: 0.02, green: 0.01, blue: 0.06, alpha: 0.55)] as CFArray, locations: [0.55, 1])!
ctx.drawRadialGradient(grad, startCenter: CGPoint(x: S/2, y: S/2), startRadius: 0, endCenter: CGPoint(x: S/2, y: S/2), endRadius: inner*0.72, options: [])
// escurece a parte de baixo (esconde o "DEVELOPER", que não cabe no quadrado)
let fade = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
    colors: [CGColor(red: 0.02, green: 0.01, blue: 0.05, alpha: 0), CGColor(red: 0.02, green: 0.01, blue: 0.05, alpha: 0.96)] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(fade, start: CGPoint(x: 0, y: CGFloat(pad) + inner*0.33), end: CGPoint(x: 0, y: CGFloat(pad) + inner*0.27), options: [.drawsAfterEndLocation])
ctx.restoreGState()

// borda fina roxa
ctx.addPath(path); ctx.setStrokeColor(CGColor(red: 0.66, green: 0.55, blue: 0.98, alpha: 0.55)); ctx.setLineWidth(3); ctx.strokePath()

let rep = NSBitmapImageRep(cgImage: ctx.makeImage()!)
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: "icon_1024.png"))
