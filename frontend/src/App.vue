
<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from './services/api'
import NowPlaying from './components/player/NowPlaying.vue'
import PlayerControls from './components/player/PlayerControls.vue'
import VolumeControl from './components/player/VolumeControl.vue'

const songs = ref([])
const player = ref({
  title: 'Nothing playing',
  artist: '',
  path: '',
  position: 0,
  duration: 0,
  paused: true
})

const volume = ref(85)
const loading = ref(true)
const error = ref('')
const selectedPath = ref('')

let statusTimer = null

async function loadSongs() {
  try {
    songs.value = await api.getSongs('music')
  } catch (err) {
    error.value = `Cannot load music library: ${err.message}`
  } finally {
    loading.value = false
  }
}

async function updateStatus() {
  try {
    const status = await api.getStatus()

    if (status.status === 'error') {
      player.value = {
        title: 'Nothing playing',
        artist: '',
        path: '',
        position: 0,
        duration: 0,
        paused: true
      }
      return
    }

    player.value = status
  } catch (err) {
    console.error('Status update failed:', err)
  }
}

async function playSong(song) {
  try {
    selectedPath.value = song.path
    await api.play(song.path, song.type || 'music')
    await updateStatus()
  } catch (err) {
    error.value = `Playback failed: ${err.message}`
  }
}

async function togglePlayback() {
  try {
    if (player.value.paused) {
      await api.resume()
    } else {
      await api.pause()
    }

    await updateStatus()
  } catch (err) {
    error.value = err.message
  }
}

async function stopPlayback() {
  try {
    await api.stop()
    await updateStatus()
  } catch (err) {
    error.value = err.message
  }
}

async function changeVolume() {
  try {
    await api.setVolume(volume.value)
  } catch (err) {
    error.value = `Volume adjustment failed: ${err.message}`
  }
}

async function loadVolume() {
  try {
    const result = await api.getVolume()
    volume.value = Number(result.volume)
  } catch (err) {
    console.error('Volume loading failed:', err)
  }
}

onMounted(async () => {
  await Promise.all([
    loadSongs(),
    updateStatus(),
    loadVolume()
  ])

  statusTimer = setInterval(updateStatus, 2000)
})

onUnmounted(() => {
  if (statusTimer) clearInterval(statusTimer)
})
</script>

<template>
  <main class="app">
    <header class="header">
      <div>
        <h1>Pi Music Console</h1>
        <p>Raspberry Pi Music Player</p>
      </div>
      <span class="connection">Flask Connected</span>
    </header>

    <section class="now-playing">
      <NowPlaying
        :title="player.title"
        :artist="player.artist"
        :position="player.position"
        :duration="player.duration"
      />

      <PlayerControls
        :paused="player.paused"
        :has-track="Boolean(player.path)"
        @toggle-playback="togglePlayback"
        @stop="stopPlayback"
      />
    </section>

    <VolumeControl
      v-model:volume="volume"
      @change="changeVolume"
    />

    <section class="library">
      <h2>My Music Library</h2>

      <p v-if="loading">Loading music library...</p>

      <p v-else-if="error" class="error">
        {{ error }}
      </p>

      <p v-else-if="songs.length === 0">
        No music found.
      </p>

      <div v-else class="song-list">
        <button
          v-for="song in songs"
          :key="song.path"
          class="song"
          :class="{ selected: selectedPath === song.path }"
          @click="playSong(song)"
        >
          <span class="play-icon">▶</span>

          <span class="song-info">
            <strong>{{ song.title || song.filename }}</strong>
            <small>
              {{ song.artist || 'Unknown artist' }}
              <span v-if="song.album">
                · {{ song.album }}
              </span>
            </small>
          </span>
        </button>
      </div>
    </section>
  </main>
</template>
