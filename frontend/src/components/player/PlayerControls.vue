<script setup>
defineProps({
  paused: {
    type: Boolean,
    required: true
  },
  hasTrack: {
    type: Boolean,
    required: true
  }
})

defineEmits(['toggle-playback', 'stop'])
</script>

<template>
  <div class="controls">
    <button @click="$emit('toggle-playback')" :disabled="!hasTrack">
      {{ paused ? '▶ Play' : 'Ⅱ Pause' }}
    </button>

    <button @click="$emit('stop')" :disabled="!hasTrack">
      ■ Stop
    </button>
  </div>
</template>
