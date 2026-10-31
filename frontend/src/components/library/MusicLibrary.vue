<script setup>
import SongItem from './SongItem.vue'

defineProps({
  songs: {
    type: Array,
    required: true
  },
  selectedPath: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['play'])
</script>

<template>
  <p v-if="songs.length === 0">
    No music found.
  </p>

  <div v-else class="song-list">
    <SongItem
      v-for="song in songs"
      :key="song.path"
      :song="song"
      :selected="selectedPath === song.path"
      @play="emit('play', $event)"
    />
  </div>
</template>
