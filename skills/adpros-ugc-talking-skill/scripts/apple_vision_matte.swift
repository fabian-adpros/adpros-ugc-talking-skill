import AVFoundation
import CoreImage
import Foundation
import Vision

// Person-only matte. A product in the hand can be erased.
//   apple-vision-matte --input clip.mp4 --output matte.mp4 --quality accurate

struct Options {
    var input = ""
    var output = ""
    var quality = "accurate"
}

func parse(_ argv: [String]) -> Options {
    var opts = Options()
    var index = 1
    while index < argv.count {
        let flag = argv[index]
        let value = index + 1 < argv.count ? argv[index + 1] : ""
        switch flag {
        case "--input": opts.input = value
        case "--output": opts.output = value
        case "--quality": opts.quality = value
        default: break
        }
        index += 2
    }
    return opts
}

let opts = parse(CommandLine.arguments)
if opts.input.isEmpty || opts.output.isEmpty {
    fputs("usage: apple-vision-matte --input clip.mp4 --output matte.mp4 --quality accurate\n", stderr)
    exit(2)
}

let asset = AVAsset(url: URL(fileURLWithPath: opts.input))
guard let track = asset.tracks(withMediaType: .video).first else {
    fputs("no video track\n", stderr)
    exit(1)
}
let reader = try AVAssetReader(asset: asset)
let readerOutput = AVAssetReaderTrackOutput(track: track, outputSettings: [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA
])
reader.add(readerOutput)
guard reader.startReading() else {
    fputs("could not read the video\n", stderr)
    exit(1)
}

let size = track.naturalSize
let fps = max(1, track.nominalFrameRate)
let writer = try AVAssetWriter(outputURL: URL(fileURLWithPath: opts.output), fileType: .mp4)
let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: Int(size.width),
    AVVideoHeightKey: Int(size.height)
])
let adaptor = AVAssetWriterInputPixelBufferAdaptor(
    assetWriterInput: input,
    sourcePixelBufferAttributes: [
        kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
        kCVPixelBufferWidthKey as String: Int(size.width),
        kCVPixelBufferHeightKey as String: Int(size.height)
    ]
)
writer.add(input)
guard writer.startWriting() else {
    fputs("could not write the matte\n", stderr)
    exit(1)
}
writer.startSession(atSourceTime: .zero)

let request = VNGeneratePersonSegmentationRequest()
switch opts.quality {
case "fast": request.qualityLevel = .fast
case "balanced": request.qualityLevel = .balanced
default: request.qualityLevel = .accurate
}
let context = CIContext()
var frame: Int64 = 0

while let sample = readerOutput.copyNextSampleBuffer() {
    guard let pixel = CMSampleBufferGetImageBuffer(sample) else { continue }
    let handler = VNImageRequestHandler(cvPixelBuffer: pixel, orientation: .up, options: [:])
    try handler.perform([request])
    guard let mask = request.results?.first?.pixelBuffer else { continue }
    let image = CIImage(cvPixelBuffer: mask).transformed(by: CGAffineTransform(
        scaleX: size.width / CGFloat(CVPixelBufferGetWidth(mask)),
        y: size.height / CGFloat(CVPixelBufferGetHeight(mask))
    ))
    var outputBuffer: CVPixelBuffer?
    CVPixelBufferPoolCreatePixelBuffer(nil, adaptor.pixelBufferPool!, &outputBuffer)
    if let outputBuffer {
        context.render(image, to: outputBuffer)
        while !input.isReadyForMoreMediaData { Thread.sleep(forTimeInterval: 0.002) }
        let time = CMTime(value: frame, timescale: CMTimeScale(fps))
        adaptor.append(outputBuffer, withPresentationTime: time)
    }
    frame += 1
}
input.markAsFinished()
let group = DispatchGroup()
group.enter()
writer.finishWriting { group.leave() }
group.wait()
if writer.status != .completed {
    fputs("matte write failed\n", stderr)
    exit(1)
}
