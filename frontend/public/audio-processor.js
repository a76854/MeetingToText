class RecorderProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0]
    if (input && input.length > 0) {
      const channel = input[0]
      if (channel && channel.length > 0) {
        this.port.postMessage(channel)
      }
    }
    return true
  }
}

registerProcessor('recorder-processor', RecorderProcessor)
