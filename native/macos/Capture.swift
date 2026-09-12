import AppKit
import AVFoundation
import ScreenCaptureKit
import CoreMedia
import Darwin

// A private Unix socket carries versioned audio to Explore. No audio files or logs.
var captureOutput = FileHandle.standardOutput
var captureInput = FileHandle.standardInput
let outputLock = NSLock()
func emit(_ object: [String: Any]) {
    outputLock.lock(); defer { outputLock.unlock() }
    if let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) {
        captureOutput.write(data + Data([10]))
    }
}

final class PCMConverter {
    private var converter: AVAudioConverter?
    private var format: AVAudioFormat?
    func convert(_ buffer: AVAudioPCMBuffer) throws -> Data {
        let output = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000,
                                   channels: 1, interleaved: true)!
        if format != buffer.format {
            format = buffer.format
            converter = AVAudioConverter(from: buffer.format, to: output)
        }
        guard let converter = converter else { throw CaptureFailure.audioFormat }
        let capacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) * 16000 / buffer.format.sampleRate) + 32)
        guard let result = AVAudioPCMBuffer(pcmFormat: output, frameCapacity: capacity) else {
            throw CaptureFailure.audioFormat
        }
        var supplied = false
        var error: NSError?
        let status = converter.convert(to: result, error: &error) { _, state in
            if supplied { state.pointee = .noDataNow; return nil }
            supplied = true
            state.pointee = .haveData
            return buffer
        }
        guard status != .error, error == nil, let samples = result.int16ChannelData else {
            throw CaptureFailure.audioFormat
        }
        return Data(bytes: samples[0], count: Int(result.frameLength) * 2)
    }
}
enum CaptureFailure: Error { case audioFormat }

final class AudioMux {
    private let lock = NSLock()
    private var buffers = ["microphone": Data(), "system": Data()]
    private var sequence = 0
    private var timer: DispatchSourceTimer?
    var fail: (String) -> Void = { _ in }
    func append(_ data: Data, channel: String) {
        lock.lock()
        buffers[channel]!.append(data)
        let overflow = buffers[channel]!.count > 96000
        lock.unlock()
        if overflow { fail("audio_overflow") }
    }
    func start() {
        lock.lock()
        buffers = ["microphone": Data(), "system": Data()]
        lock.unlock()
        let timer = DispatchSource.makeTimerSource(queue: DispatchQueue(label: "explore.audio.pipe"))
        timer.schedule(deadline: .now() + .milliseconds(100), repeating: .milliseconds(100))
        timer.setEventHandler { [weak self] in self?.tick() }
        self.timer = timer
        timer.resume()
    }
    private func tick() {
        for channel in ["microphone", "system"] {
            lock.lock()
            let size = min(3200, buffers[channel]!.count)
            var data = Data(buffers[channel]!.prefix(size))
            buffers[channel]!.removeFirst(size)
            lock.unlock()
            if size < 3200 { data.append(Data(count: 3200 - size)) }
            emit(["type": "audio", "channel": channel, "sequence": sequence,
                  "pcm": data.base64EncodedString()])
        }
        sequence += 1
    }
    func stop() { timer?.cancel(); timer = nil }
}

final class Capture: NSObject, SCStreamOutput, SCStreamDelegate {
    let engine = AVAudioEngine()
    let mux = AudioMux()
    let micConverter = PCMConverter()
    let systemConverter = PCMConverter()
    var stream: SCStream?
    var stopping = false
    var tapped = false

    func start() async {
        mux.fail = { [weak self] code in
            guard let capture = self else { return }
            Task { await capture.stop(code) }
        }
        guard await AVCaptureDevice.requestAccess(for: .audio) else {
            await stop("microphone_permission"); return
        }
        guard CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess() else {
            await stop("screen_permission"); return
        }
        do {
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
            guard let display = content.displays.first else { await stop("system_capture"); return }
            let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
            let config = SCStreamConfiguration()
            config.capturesAudio = true
            config.excludesCurrentProcessAudio = true
            config.sampleRate = 16000
            config.channelCount = 1
            config.width = 2; config.height = 2
            config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
            let stream = SCStream(filter: filter, configuration: config, delegate: self)
            self.stream = stream
            // No .screen output is registered; only audio leaves ScreenCaptureKit.
            try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: DispatchQueue(label: "explore.audio.system"))
            let input = engine.inputNode
            let format = input.outputFormat(forBus: 0)
            guard format.sampleRate > 0, format.channelCount > 0 else { await stop("audio_device"); return }
            input.installTap(onBus: 0, bufferSize: 4096, format: format) { [weak self] buffer, _ in
                guard let self = self else { return }
                do { self.mux.append(try self.micConverter.convert(buffer), channel: "microphone") }
                catch { Task { await self.stop("audio_format") } }
            }
            tapped = true
            try engine.start()
            try await stream.startCapture()
            emit(["type": "ready", "version": 1, "sample_rate": 16000])
            mux.start()
        } catch { await stop("system_capture") }
    }
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of outputType: SCStreamOutputType) {
        guard outputType == .audio, sampleBuffer.isValid,
              let description = sampleBuffer.formatDescription,
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(description),
              let format = AVAudioFormat(streamDescription: asbd) else { return }
        let list = AudioBufferList.allocate(maximumBuffers: Int(format.channelCount))
        defer { free(list.unsafeMutablePointer) }
        var block: CMBlockBuffer?
        let result = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer, bufferListSizeNeededOut: nil, bufferListOut: list.unsafeMutablePointer,
            bufferListSize: AudioBufferList.sizeInBytes(maximumBuffers: Int(format.channelCount)),
            blockBufferAllocator: nil, blockBufferMemoryAllocator: nil, flags: 0, blockBufferOut: &block)
        guard result == noErr,
              let buffer = AVAudioPCMBuffer(pcmFormat: format, bufferListNoCopy: list.unsafePointer) else {
            Task { await stop("audio_format") }; return
        }
        do {
            let data = try withExtendedLifetime(block) { try systemConverter.convert(buffer) }
            mux.append(data, channel: "system")
        }
        catch { Task { await stop("audio_format") } }
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        Task { await stop("system_capture") }
    }
    @MainActor func stop(_ code: String? = nil) async {
        if stopping { return }; stopping = true
        mux.stop()
        if tapped { engine.inputNode.removeTap(onBus: 0) }
        engine.stop()
        if let stream = stream { try? await stream.stopCapture() }
        if let code = code { emit(["type": "error", "code": code]) }
        else { emit(["type": "stopped"]) }
        exit(code == nil ? 0 : 1)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    let capture = Capture()
    var item: NSStatusItem?
    func applicationDidFinishLaunching(_ notification: Notification) {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.title = "◎ Explore capture"
        let menu = NSMenu()
        menu.addItem(withTitle: "Stop audio capture", action: #selector(stopCapture), keyEquivalent: "")
        menu.items.first?.target = self
        item.menu = menu; self.item = item
        DispatchQueue.global().async {
            _ = captureInput.readDataToEndOfFile()
            // Exit even if a macOS permission dialog is blocking the main thread.
            // Closing the backend channel must never leave background recording alive.
            exit(0)
        }
        Task { await capture.start() }
    }
    @objc func stopCapture() { Task { await capture.stop() } }
}

// Connect before requesting permissions, so the backend can cancel even during a prompt.
if let index = CommandLine.arguments.firstIndex(of: "--socket"),
   CommandLine.arguments.count > index + 1 {
    let path = CommandLine.arguments[index + 1]
    var address = sockaddr_un()
    address.sun_family = sa_family_t(AF_UNIX)
    guard path.utf8.count < MemoryLayout.size(ofValue: address.sun_path) else { exit(2) }
    withUnsafeMutablePointer(to: &address.sun_path) { pointer in
        pointer.withMemoryRebound(to: CChar.self, capacity: 104) { target in
            _ = path.withCString { strcpy(target, $0) }
        }
    }
    let descriptor = socket(AF_UNIX, SOCK_STREAM, 0)
    guard descriptor >= 0 else { exit(2) }
    let result = withUnsafePointer(to: &address) { pointer in
        pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            Darwin.connect(descriptor, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
        }
    }
    guard result == 0 else { Darwin.close(descriptor); exit(2) }
    captureInput = FileHandle(fileDescriptor: descriptor, closeOnDealloc: false)
    captureOutput = FileHandle(fileDescriptor: descriptor, closeOnDealloc: false)
}

if CommandLine.arguments.contains("--transport-test") {
    // Launch Services / IPC acceptance test: no audio device or permission requests.
    emit(["type": "ready", "version": 1, "sample_rate": 16000])
    _ = captureInput.readDataToEndOfFile()
    exit(0)
}

if CommandLine.arguments.contains("--self-test") {
    // Synthetic PCM conversion only: never requests permission or opens a device.
    let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48000,
                               channels: 1, interleaved: false)!
    let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 4800)!
    buffer.frameLength = 4800
    for i in 0..<4800 { buffer.floatChannelData![0][i] = 0.25 }
    let data = try PCMConverter().convert(buffer)
    precondition(data.count > 2000 && data.count <= 3264)
    precondition(data.count % 2 == 0)
    print("PCM conversion passed")
} else {
    let app = NSApplication.shared
    let delegate = AppDelegate()
    app.delegate = delegate
    app.setActivationPolicy(.accessory)
    app.run()
}
