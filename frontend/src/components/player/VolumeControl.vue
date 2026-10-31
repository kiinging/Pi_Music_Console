<script setup>
defineProps({
  volume: {
    type: Number,
    required: true
  }
})

const emit = defineEmits(['update:volume', 'change'])

function updateVolume(event) {
  emit('update:volume', Number(event.target.value))
}
</script>

<template>
  <section class="volume">
    <label>
      Volume: {{ volume }}%
    </label>

    <input
      :value="volume"
      type="range"
      min="0"
      max="100"
      @input="updateVolume"
      @change="emit('change')"
    />
  </section>
</template>
