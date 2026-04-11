// MicProbe.swift — diagnostic. Opens the mic for 6 seconds and prints RMS
// energy of every buffer to stderr so we can see whether audio is reaching us.
//
// Build: swiftc -O MicProbe.swift -o micprobe
// Run:   ./micprobe

import Foundation
import AVFoundation

let stderr = FileHandle.standardError
func log(_ s: String) { if let d = (s + "\n").data(using: .utf8) { stderr.write(d) } }

let engine = AVAudioEngine()
let input = engine.inputNode
let format = input.outputFormat(forBus: 0)
log("input format: sr=\(format.sampleRate) ch=\(format.channelCount)")

var bufferCount = 0
var maxRMS: Float = 0

input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
    guard let ch = buffer.floatChannelData?[0] else { return }
    let n = Int(buffer.frameLength)
    if n == 0 { return }
    var sum: Float = 0
    for i in 0..<n { sum += ch[i] * ch[i] }
    let rms = (sum / Float(n)).squareRoot()
    bufferCount += 1
    if rms > maxRMS { maxRMS = rms }
    if bufferCount % 10 == 0 {
        log(String(format: "buf=%4d  rms=%.5f  max=%.5f", bufferCount, rms, maxRMS))
    }
}

do {
    try engine.start()
    log("engine started — recording 6 seconds. SAY 'HELLO HELLO HELLO' NOW")
} catch {
    log("engine.start() failed: \(error)")
    exit(1)
}

Thread.sleep(forTimeInterval: 6.0)
engine.stop()
log("done. total buffers=\(bufferCount), peak rms=\(maxRMS)")
if maxRMS < 0.0001 {
    log("VERDICT: mic delivered SILENCE — TCC is blocking input")
} else if maxRMS < 0.012 {
    log("VERDICT: mic alive but voice didn't cross 0.012 — speak louder or lower the threshold")
} else {
    log("VERDICT: mic alive and crossing threshold — should be working")
}
