// Passes raw microphone frames from the audio thread to the page, which resamples
// them to 16 kHz PCM16 for Gemini Live.
class MicCapture extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) this.port.postMessage(channel.slice(0));
    return true;
  }
}
registerProcessor("mic-capture", MicCapture);
