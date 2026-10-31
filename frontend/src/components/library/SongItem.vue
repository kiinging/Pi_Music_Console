<script setup>
const props = defineProps({
  song: {
    type: Object,
    required: true
  },
  selected: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['play'])
</script>

<template>
  <button
    class="song"
    :class="{ selected }"
    @click="emit('play', props.song)"
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
</template>
