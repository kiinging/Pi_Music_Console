
const API_BASE = '/api'

// General GET request
async function get(endpoint) {
  const response = await fetch(`${API_BASE}${endpoint}`)

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`)
  }

  return response.json()
}

// General POST request
async function post(endpoint, data = {}) {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  })

  const result = await response.json()

  if (!response.ok) {
    throw new Error(result.error || `API error: ${response.status}`)
  }

  return result
}

// Music player API
export const api = {
  // Library
  getSongs(type = 'music') {
    return get(`/songs?type=${encodeURIComponent(type)}`)
  },

  // Playback
  getStatus() {
    return get('/status')
  },

  play(path, type = 'music') {
    return post('/play', { path, type })
  },

  pause() {
    return post('/pause')
  },

  resume() {
    return post('/resume')
  },

  stop() {
    return post('/stop')
  },

  // Volume
  getVolume() {
    return get('/volume')
  },

  setVolume(volume) {
    return post('/volume', { volume })
  }
}
