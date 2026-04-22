import Foundation
import PDFKit
import Vision
import AppKit

func renderPage(_ page: PDFPage) -> CGImage? {
    let pageRect = page.bounds(for: .mediaBox)
    let scale: CGFloat = 2.0
    let width = Int(pageRect.width * scale)
    let height = Int(pageRect.height * scale)

    guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
          let context = CGContext(
            data: nil,
            width: max(width, 1),
            height: max(height, 1),
            bitsPerComponent: 8,
            bytesPerRow: 0,
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
          ) else {
        return nil
    }

    context.setFillColor(NSColor.white.cgColor)
    context.fill(CGRect(x: 0, y: 0, width: CGFloat(width), height: CGFloat(height)))
    context.saveGState()
    context.translateBy(x: 0, y: CGFloat(height))
    context.scaleBy(x: scale, y: -scale)
    page.draw(with: .mediaBox, to: context)
    context.restoreGState()

    return context.makeImage()
}

func ocr(_ image: CGImage) -> String {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["it-IT", "en-US"]

    let handler = VNImageRequestHandler(cgImage: image, options: [:])
    try? handler.perform([request])

    let observations = request.results ?? []
    return observations.compactMap { observation in
        observation.topCandidates(1).first?.string
    }.joined(separator: "\n")
}

guard CommandLine.arguments.count > 1 else {
    fputs("Percorso PDF mancante\n", stderr)
    exit(1)
}

let pdfPath = CommandLine.arguments[1]
guard let document = PDFDocument(url: URL(fileURLWithPath: pdfPath)) else {
    fputs("Impossibile aprire il PDF\n", stderr)
    exit(1)
}

var chunks: [String] = []

for index in 0..<document.pageCount {
    guard let page = document.page(at: index) else { continue }
    let nativeText = page.string?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    if nativeText.count > 20 {
        chunks.append(nativeText)
        continue
    }
    if let image = renderPage(page) {
        let recognized = ocr(image).trimmingCharacters(in: .whitespacesAndNewlines)
        if !recognized.isEmpty {
            chunks.append(recognized)
        }
    }
}

print(chunks.joined(separator: "\n"))
