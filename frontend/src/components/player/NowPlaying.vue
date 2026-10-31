<script setup>
defineProps({
  title: {
    type: String,
    required: true
  },
  artist: {
    type: String,
    required: true
  },
  position: {
    type: [Number, String],
    required: true
  },
  duration: {
    type: [Number, String],
    required: true
  }
})

function formatTime(seconds) {
  const value = Math.floor(Number(seconds) || 0)
  const minutes = Math.floor(value / 60)
  const remaining = value % 60

  return `${minutes}:${String(remaining).padStart(2, '0')}`
}
</script>

<template>
  <div>
    <p class="section-label">NOW PLAYING</p>
    <h2>{{ title }}</h2>
    <p class="artist">{{ artist }}</p>
    <p class="time">
      {{ formatTime(position) }} /
      {{ formatTime(duration) }}
    </p>
  </div>
</template>
