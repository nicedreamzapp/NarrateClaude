// Listen.swift — continuous on-device dictation for NarrateClaude
//
// Uses macOS SFSpeechRecognizer (the same on-device engine that powers the
// system Dictation feature). Runs ONE continuous recognition task at a time
// and detects end-of-utterance based on **partial-result stability**: if the
// recognized text stops changing for `stabilityDuration` seconds, we call
// endAudio() to force the recognizer to finalize. This is robust against
// background noise, unlike RMS-based silence detection.
//
// Auto-pauses while `afplay` is running so the cloned voice (Pocket TTS via
// the `speak` command) doesn't get fed back into the recognizer.
//
// Build:
//   swiftc -O Listen.swift -o listen
//
// Run:
//   ./listen
//
// Output: one transcript per line on stdout. Status messages on stderr.
//
// Env var overrides:
//   LISTEN_STABILITY_SEC      how long partial text must be unchanged to finalize (default 2.5)
//   LISTEN_MAX_UTTER_SEC      hard cap on a single utterance in seconds (default 60)
//   LISTEN_MAX_SESSION_SEC    preventive process recycle after this many seconds (default 300)
//   LISTEN_WEDGE_BACKLOG      how many unprocessed buffers triggers a wedge exit (default 200)
//   LISTEN_SILENT_WEDGE_SEC   no recognition events for this long while audio is active = wedge (default 20)
//   LISTEN_AUDIO_THRESHOLD    sample max-abs above this counts as "real audio" not silence (default 0.01)
//   LISTEN_DEBUG              set to "1" for verbose diagnostic logging
//
// Exit codes:
//   0  clean exit (preventive recycle, stdin closed, etc.)
//   2  speech recognition not authorized
//   3  could not create SFSpeechRecognizer
//   4  could not start audio engine
//   99 watchdog detected wedged listener queue (sync XPC hang in SFSpeech)

import Foundation
import Speech
import AVFoundation

// MARK: - Tunables (env-overridable)

let stabilityDuration: Double = {
    if let s = ProcessInfo.processInfo.environment["LISTEN_STABILITY_SEC"], let d = Double(s) { return d }
    return 2.5
}()

let maxUtteranceDuration: Double = {
    if let s = ProcessInfo.processInfo.environment["LISTEN_MAX_UTTER_SEC"], let d = Double(s) { return d }
    return 60.0
}()

let maxSessionDuration: Double = {
    if let s = ProcessInfo.processInfo.environment["LISTEN_MAX_SESSION_SEC"], let d = Double(s) { return d }
    return 300.0   // 5 minutes — preventive recycle to dodge SFSpeech daemon wedges
}()

let wedgeBacklogThreshold: Int = {
    if let s = ProcessInfo.processInfo.environment["LISTEN_WEDGE_BACKLOG"], let i = Int(s) { return i }
    return 200     // ~4-5s of audio buffers piled up = listener queue is wedged
}()

// Silent-wedge detector: SFSpeech sometimes goes quiet without crashing or
// piling up backlog — audio is being fed and processed normally, but the
// recognizer just stops emitting partial/final events. We catch this by
// tracking "time since last recognition event" against "time since last
// non-silent audio buffer". If real speech audio is flowing AND no events
// have come back for silentWedgeMaxSec, we've wedged silently and exit 99.
let silentWedgeMaxSec: Double = {
    if let s = ProcessInfo.processInfo.environment["LISTEN_SILENT_WEDGE_SEC"], let d = Double(s) { return d }
    return 20.0
}()

let silentWedgeAudioThreshold: Float = {
    if let s = ProcessInfo.processInfo.environment["LISTEN_AUDIO_THRESHOLD"], let d = Float(s) { return d }
    return 0.01
}()

// How recent the last "real audio" buffer must be to count as a live
// speaking session (vs. user just sitting silent). Keep this short so a
// brief pause between phrases doesn't reset the wedge clock unfairly.
let silentWedgeAudioRecencySec: Double = 5.0

let pausePollInterval: TimeInterval = 0.15
let watchdogPollInterval: TimeInterval = 5.0

// MARK: - Globals

let stderr = FileHandle.standardError
let stdout = FileHandle.standardOutput

func log(_ msg: String) {
    if let data = (msg + "\n").data(using: .utf8) { stderr.write(data) }
}

func emit(_ line: String) {
    let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else { return }
    if let data = (trimmed + "\n").data(using: .utf8) { stdout.write(data) }
}

// Atomic-ish flag set by the pause poller, read by the audio tap
final class AtomicBool {
    private var value: Bool
    private let lock = NSLock()
    init(_ v: Bool) { self.value = v }
    func get() -> Bool { lock.lock(); defer { lock.unlock() }; return value }
    func set(_ v: Bool) { lock.lock(); value = v; lock.unlock() }
}

// Lock-protected counter shared between the audio thread, the listener serial
// queue, and the watchdog thread. Used by the watchdog to detect a wedged
// listener queue (audio still arriving but handleBuffer no longer running).
final class AtomicInt {
    private var value: Int
    private let lock = NSLock()
    init(_ v: Int) { self.value = v }
    func get() -> Int { lock.lock(); defer { lock.unlock() }; return value }
    func increment() { lock.lock(); value &+= 1; lock.unlock() }
}

// Lock-protected timestamp (seconds since 1970) shared with the watchdog
// thread. Used by the silent-wedge detector to compare the most recent
// recognition event against the most recent buffer of real (non-silent)
// audio.
final class AtomicDouble {
    private var value: Double
    private let lock = NSLock()
    init(_ v: Double) { self.value = v }
    func get() -> Double { lock.lock(); defer { lock.unlock() }; return value }
    func set(_ v: Double) { lock.lock(); value = v; lock.unlock() }
}

let speakIsPlaying = AtomicBool(false)
let bufferReceivedCount = AtomicInt(0)   // bumped on the audio thread (pre-dispatch)
let bufferProcessedCount = AtomicInt(0)  // bumped on the listener serial queue
let sessionStartTime = Date()
// Silent-wedge tracking. lastEventTime starts "now" so we don't false-trip
// during the first silentWedgeMaxSec of the session. lastSpeechAudioTime
// starts at 0 so the watchdog won't think audio is active until we've
// actually seen a non-silent buffer.
let lastEventTime = AtomicDouble(Date().timeIntervalSince1970)
let lastSpeechAudioTime = AtomicDouble(0)

// Watchdog: detect a wedged listener serial queue and force a process exit
// so the dispatch wrapper can respawn us. The classic failure mode is
// SFSpeechRecognizer.recognitionTask(with:) hanging on a synchronous XPC
// call into Apple's speech daemon, which blocks every other handler on the
// listener queue (including handleBuffer). When that happens audio buffers
// keep arriving on the audio thread but bufferProcessedCount stops growing
// while bufferReceivedCount keeps growing.
//
// Also enforces a max session lifetime as a preventive recycle — even if
// nothing is wedged, recreating the recognizer periodically dodges
// long-tail daemon issues entirely.
func startWatchdog() {
    DispatchQueue.global(qos: .utility).async {
        while true {
            Thread.sleep(forTimeInterval: watchdogPollInterval)

            let received = bufferReceivedCount.get()
            let processed = bufferProcessedCount.get()
            let backlog = received - processed

            if backlog > wedgeBacklogThreshold {
                log("WATCHDOG: listener queue wedged (received=\(received) processed=\(processed) backlog=\(backlog)) — exiting 99 for respawn")
                // Flush stderr before bailing
                try? FileHandle.standardError.synchronize()
                exit(99)
            }

            // Silent-wedge check: live speech audio is being captured but
            // SFSpeech has stopped emitting recognition events. Skip while
            // afplay (the cloned voice) is paused since we deliberately
            // cancel the task in that state.
            if !speakIsPlaying.get() {
                let now = Date().timeIntervalSince1970
                let lastAud = lastSpeechAudioTime.get()
                let lastEvt = lastEventTime.get()
                let timeSinceAudio = now - lastAud
                let timeSinceEvent = now - lastEvt
                if lastAud > 0
                   && timeSinceAudio < silentWedgeAudioRecencySec
                   && timeSinceEvent > silentWedgeMaxSec {
                    log(String(format: "WATCHDOG: silent wedge — audio active %.1fs ago but no recognition events for %.1fs, exiting 99 for respawn", timeSinceAudio, timeSinceEvent))
                    try? FileHandle.standardError.synchronize()
                    exit(99)
                }
            }

            let age = Date().timeIntervalSince(sessionStartTime)
            if age >= maxSessionDuration {
                log(String(format: "WATCHDOG: max session age %.0fs reached — exiting 0 for clean recycle", maxSessionDuration))
                try? FileHandle.standardError.synchronize()
                exit(0)
            }
        }
    }
}

// Poll for `afplay` (used by the speak script) so we can pause listening
// while the cloned voice is talking.
func startPausePoller() {
    DispatchQueue.global(qos: .utility).async {
        while true {
            let task = Process()
            task.launchPath = "/usr/bin/pgrep"
            task.arguments = ["-x", "afplay"]
            task.standardOutput = Pipe()
            task.standardError = Pipe()
            do {
                try task.run()
                task.waitUntilExit()
                speakIsPlaying.set(task.terminationStatus == 0)
            } catch {
                speakIsPlaying.set(false)
            }
            Thread.sleep(forTimeInterval: pausePollInterval)
        }
    }
}

// MARK: - Listener

final class Listener {
    let recognizer: SFSpeechRecognizer
    let audioEngine = AVAudioEngine()

    // Serial queue for all state mutation — buffer handler, result callback,
    // and restart logic all hop onto this so we don't need locks.
    let queue = DispatchQueue(label: "narrateclaude.listener")

    var currentRequest: SFSpeechAudioBufferRecognitionRequest? = nil
    var currentTask: SFSpeechRecognitionTask? = nil
    var lastPartialText: String = ""
    var lastPartialChangeTime: Date? = nil
    var taskStartTime: Date = Date()
    var finalizing: Bool = false

    let debug = ProcessInfo.processInfo.environment["LISTEN_DEBUG"] == "1"
    var debugBufferCount = 0

    init?() {
        guard let r = SFSpeechRecognizer(locale: Locale(identifier: "en-US")) else {
            log("Could not create SFSpeechRecognizer for en-US")
            return nil
        }
        guard r.isAvailable else {
            log("SFSpeechRecognizer is not currently available")
            return nil
        }
        self.recognizer = r
    }

    func start() throws {
        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)

        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            // Bump the received counter on the audio thread BEFORE dispatching.
            // This is what lets the watchdog notice when handleBuffer stops
            // draining the queue (received keeps growing, processed doesn't).
            bufferReceivedCount.increment()
            self?.queue.async {
                self?.handleBuffer(buffer)
            }
        }

        audioEngine.prepare()
        try audioEngine.start()
        log(String(format: "Listening (stability=%.1fs, max=%.0fs)...",
                   stabilityDuration, maxUtteranceDuration))

        // Kick off the first recognition task
        queue.async { [weak self] in self?.startRecognition() }
    }

    // Must be called on self.queue
    private func startRecognition() {
        currentTask?.cancel()
        currentTask = nil
        currentRequest = nil

        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition {
            req.requiresOnDeviceRecognition = true
        }
        req.taskHint = .dictation
        currentRequest = req
        lastPartialText = ""
        lastPartialChangeTime = nil
        taskStartTime = Date()
        finalizing = false

        if debug { log("DBG startRecognition onDevice=\(recognizer.supportsOnDeviceRecognition)") }

        currentTask = recognizer.recognitionTask(with: req) { [weak self] result, error in
            guard let self = self else { return }
            self.queue.async {
                self.handleResult(result: result, error: error)
            }
        }
    }

    // Must be called on self.queue
    private func handleResult(result: SFSpeechRecognitionResult?, error: Error?) {
        // Heartbeat for the silent-wedge watchdog — any sign of life from
        // SFSpeech (partial, final, or non-cancelled error) counts.
        if result != nil || (error as NSError?)?.code != 216 {
            lastEventTime.set(Date().timeIntervalSince1970)
        }
        if let result = result {
            let txt = result.bestTranscription.formattedString
                .trimmingCharacters(in: .whitespacesAndNewlines)

            if result.isFinal {
                // Prefer the final result's text. If empty, fall back to the
                // last stable partial — sometimes SFSpeech's final callback
                // carries no text after a forced endAudio().
                let finalText = txt.isEmpty ? lastPartialText : txt
                if debug { log("DBG FINAL \"\(finalText)\" (resultTxt=\"\(txt)\")") }
                if !finalText.isEmpty { emit(finalText) }
                startRecognition()
                return
            }

            // Partial
            if txt != lastPartialText {
                if debug { log("DBG partial \"\(txt)\"") }
                lastPartialText = txt
                lastPartialChangeTime = Date()
            }
        }

        if let error = error {
            let nserr = error as NSError
            // 216 = task cancelled (expected during restart). 203/1110 = no speech.
            if nserr.code == 216 { return }
            if debug {
                log("DBG recog error code=\(nserr.code) domain=\(nserr.domain) desc=\(nserr.localizedDescription)")
            }
            // For "no speech detected" we just restart quietly
            if nserr.code == 203 || nserr.code == 1110 {
                startRecognition()
                return
            }
            // Unknown error — back off briefly and restart
            queue.asyncAfter(deadline: .now() + 0.5) { [weak self] in
                self?.startRecognition()
            }
        }
    }

    // Must be called on self.queue
    private func handleBuffer(_ buffer: AVAudioPCMBuffer) {
        // Bump the processed counter — this is the watchdog's heartbeat.
        // If this stops growing while bufferReceivedCount keeps growing,
        // the listener queue is wedged and the watchdog will exit(99).
        bufferProcessedCount.increment()

        // Track real-audio recency for the silent-wedge watchdog. Cheap
        // max-abs scan over the buffer (≤1024 frames) — anything above the
        // threshold means the user is actually making noise into the mic.
        if !speakIsPlaying.get(), let chans = buffer.floatChannelData {
            let frames = Int(buffer.frameLength)
            if frames > 0 {
                let samples = chans[0]
                var maxAbs: Float = 0
                for i in 0..<frames {
                    let v = abs(samples[i])
                    if v > maxAbs { maxAbs = v }
                }
                if maxAbs >= silentWedgeAudioThreshold {
                    lastSpeechAudioTime.set(Date().timeIntervalSince1970)
                }
            }
        }

        // If the cloned voice is playing, drop the buffer and cancel any
        // in-progress utterance so we don't capture our own audio.
        if speakIsPlaying.get() {
            if currentRequest != nil {
                if debug { log("DBG pause (afplay running)") }
                currentTask?.cancel()
                currentRequest = nil
                currentTask = nil
                lastPartialText = ""
                lastPartialChangeTime = nil
            }
            return
        }

        // If we don't have an active task (e.g. just came out of afplay pause),
        // start one.
        if currentRequest == nil {
            startRecognition()
            return
        }

        // If we've already called endAudio() and are waiting for the final
        // callback, stop feeding audio — per Apple's API contract you must
        // not append buffers after endAudio().
        if finalizing { return }

        // Feed the audio to the recognizer
        currentRequest?.append(buffer)

        if debug {
            debugBufferCount += 1
            if debugBufferCount % 80 == 0 {
                log(String(format: "DBG heartbeat bufs=%d partial=\"%@\"",
                           debugBufferCount, lastPartialText))
            }
        }

        // Endpoint detection: if we have partial text AND it hasn't changed
        // for `stabilityDuration`, force the recognizer to finalize.
        let now = Date()
        let taskAge = now.timeIntervalSince(taskStartTime)

        // Hard cap: cut off runaway utterances
        if taskAge >= maxUtteranceDuration && !finalizing {
            if debug { log("DBG finalizing (max duration \(maxUtteranceDuration)s reached)") }
            finalizing = true
            currentRequest?.endAudio()
            return
        }

        // Normal case: stability-based endpointing
        if !lastPartialText.isEmpty, let lastChange = lastPartialChangeTime, !finalizing {
            let stableFor = now.timeIntervalSince(lastChange)
            if stableFor >= stabilityDuration {
                if debug {
                    log(String(format: "DBG finalizing (stable %.1fs): \"%@\"",
                               stableFor, lastPartialText))
                }
                finalizing = true
                currentRequest?.endAudio()
            }
        }
    }
}

// MARK: - Main

setbuf(__stdoutp, nil)
setbuf(__stderrp, nil)

let semaphore = DispatchSemaphore(value: 0)
var authStatus: SFSpeechRecognizerAuthorizationStatus = .notDetermined

SFSpeechRecognizer.requestAuthorization { status in
    authStatus = status
    semaphore.signal()
}
semaphore.wait()

guard authStatus == .authorized else {
    log("Speech recognition not authorized (status=\(authStatus.rawValue)). Grant access in System Settings → Privacy & Security → Speech Recognition.")
    exit(2)
}

guard let listener = Listener() else {
    exit(3)
}

startPausePoller()
startWatchdog()

do {
    try listener.start()
} catch {
    log("Failed to start audio engine: \(error)")
    exit(4)
}

RunLoop.main.run()
