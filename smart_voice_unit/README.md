# Smart Voice Unit (Independent Plugin)

This is a standalone voice control system for the Pi Music Console. It is designed to run as a separate process so it does not affect the stability of the main music player.

## Hardware Support
- **Respeaker XVF3800** (USB 4-Mic Array)
- Raspberry Pi 5

## Setup
1. Enter this directory:
   ```bash
   cd smart_voice_unit
   ```
2. Run the setup script (requires internet):
   ```bash
   chmod +x setup_voice.sh
   ./setup_voice.sh
   ```

## Usage
Start the voice controller in a separate terminal window:
```bash
python3 voice_controller.py
```

### Voice Commands
1. Wake word: **"Hello Sarawak"**
2. Wait for the "Hello!!" response on screen.
3. Say your command:
   - *"Play [Song/Artist Name]"* (e.g., "Play Taylor Swift")
   - *"Good Morning"*
   - *"Thank you"* (Returns to player screen)
   - *"Volume Up / Down"*
   - *"Stop / Pause / Resume"*

## Safety Features
- **Decoupled**: If this script crashes, the music keeps playing.
- **Offline**: No internet required once models are downloaded.
- **Hardware AEC**: Uses the XVF3800's internal processing to hear you even while music is loud.

## Removal
If you don't want the feature, simply `Ctrl+C` the script or delete the `smart_voice_unit` folder. No changes were made to your main project files.
