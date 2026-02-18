#!/usr/bin/env python3
"""
All-in-one dispatch transcription processor.
Watches a folder, transcribes new files, and moves them to processed folder.

Works on both Raspberry Pi (faster-whisper) and Mac (standard whisper).
Auto-detects which environment it's running in.
"""

import os
import sys
import time
import json
import csv
import shutil
import re
from pathlib import Path
from datetime import datetime

# Pushover notification support
try:
    from pushover_notify import send_pushover, format_dispatch_message
    PUSHOVER_AVAILABLE = True
except ImportError:
    PUSHOVER_AVAILABLE = False

# Try to import the appropriate whisper library
USING_FASTER_WHISPER = False
try:
    from faster_whisper import WhisperModel
    USING_FASTER_WHISPER = True
    print("Using faster-whisper (Pi mode)")
except ImportError:
    try:
        import whisper
        print("Using standard whisper (Mac mode)")
    except ImportError:
        print("ERROR: Neither faster-whisper nor openai-whisper is installed!")
        print("\nInstall with:")
        print("  Pi:  pip3 install faster-whisper rapidfuzz --break-system-packages")
        print("  Mac: pip install openai-whisper rapidfuzz 'numpy<2'")
        sys.exit(1)

try:
    from rapidfuzz import fuzz, process
except ImportError:
    print("WARNING: rapidfuzz not installed. Fuzzy matching disabled.")
    print("Install with: pip install rapidfuzz")
    fuzz = None
    process = None

# ============================================================================
# CONFIGURATION
# ============================================================================

# Folders
WATCH_FOLDER = os.getenv('WATCH_FOLDER', './recordings')
PROCESSED_FOLDER = os.getenv('PROCESSED_FOLDER', './processed')
OUTPUT_CSV = os.getenv('OUTPUT_CSV', 'transcriptions.csv')
CONFIG_FILE = os.getenv('CONFIG_FILE', 'transcription_config.json')

# Model settings
if USING_FASTER_WHISPER:
    MODEL_SIZE = os.getenv('MODEL_SIZE', 'base')  # Pi: tiny, base, small
    DEVICE = "cpu"
    COMPUTE_TYPE = "int8"
else:
    MODEL_SIZE = os.getenv('MODEL_SIZE', 'small')  # Mac: small, medium
    DEVICE = "cpu"

CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '2'))  # seconds

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def load_config(config_path=CONFIG_FILE):
    """Load correction dictionaries and vocabulary from config file"""
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return json.load(f)
    return {
        "exact_corrections": {},
        "place_names": [],
        "prompt_vocabulary": "",
        "strip_dispatcher_headers": True
    }

def apply_exact_corrections(text, corrections):
    """Apply exact word/phrase replacements"""
    for wrong, right in corrections.items():
        text = text.replace(wrong, right)
        text = text.replace(wrong.lower(), right)
        text = text.replace(wrong.upper(), right.upper())
    return text

def fuzzy_correct_places(text, place_names, threshold=85):
    """Use fuzzy matching to correct place names"""
    if not place_names or not process:
        return text
    
    words = text.split()
    corrected_words = []
    
    for word in words:
        clean_word = word.strip('.,!?;:')
        match = process.extractOne(
            clean_word, 
            place_names, 
            scorer=fuzz.ratio,
            score_cutoff=threshold
        )
        
        if match:
            corrected = word.replace(clean_word, match[0])
            corrected_words.append(corrected)
        else:
            corrected_words.append(word)
    
    return ' '.join(corrected_words)

def strip_dispatcher_header(text):
    """Remove common dispatcher header patterns"""
    import re
    
    # Pattern matches: "Marinette/County Dispatch to/with Wausaukee Rescue/Fire/etc."
    # Then removes everything up to and including the period or the next sentence start
    pattern = r"^.*?(?:county\s+)?dispatch\s+(?:to|with)\s+\w+\s+(?:rescue|fire|ambulance|ems)[\.\,]?\s*"
    
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        cleaned = text[match.end():].strip()
        
        # Remove any residual fragments like "Rescue." at the start
        cleaned = re.sub(r"^(?:rescue|fire|ambulance|ems)[\.\,\s]+", "", cleaned, flags=re.IGNORECASE)
        
        # Remove leading punctuation
        cleaned = re.sub(r"^[\s,\.\-:]+", "", cleaned)
        return cleaned
    
    return text

def post_process_transcription(text, config):
    """Apply all post-processing corrections"""
    # Check for hallucinations (repetitive text)
    words = text.split()
    if len(words) > 10:
        # Count most common word
        from collections import Counter
        word_counts = Counter(words)
        most_common_word, count = word_counts.most_common(1)[0]
        
        # If any word appears more than 40% of the time, it's likely a hallucination
        if count > len(words) * 0.4:
            return "[HALLUCINATION DETECTED - LIKELY SILENCE OR POOR AUDIO]"
    
    # Strip dispatcher headers if enabled
    if config.get("strip_dispatcher_headers", True):
        text = strip_dispatcher_header(text)
    
    # Remove tone artifacts (e.g. OOOOOOO, BOOOOOOO, Boooooo)
    text = re.sub(r'\b[BObo]+[Oo]{4,}\b', '', text)
    text = re.sub(r'\s{2,}', ' ', text).strip()

    # Apply exact corrections
    text = apply_exact_corrections(text, config.get("exact_corrections", {}))
    
    # Fuzzy match place names
    text = fuzzy_correct_places(text, config.get("place_names", []))
    
    return text

# ============================================================================
# TRANSCRIPTION FUNCTIONS
# ============================================================================

def initialize_model():
    """Load the appropriate Whisper model"""
    print(f"Loading model: {MODEL_SIZE}...")
    start = time.time()
    
    if USING_FASTER_WHISPER:
        model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    else:
        model = whisper.load_model(MODEL_SIZE)
    
    elapsed = time.time() - start
    print(f"Model loaded in {elapsed:.1f}s\n")
    return model

def transcribe_audio(model, audio_path, prompt, config):
    """Transcribe audio file and return processed text"""
    start_time = time.time()
    
    if USING_FASTER_WHISPER:
        # faster-whisper
        segments, info = model.transcribe(
            audio_path,
            initial_prompt=prompt,
            language="en",
            beam_size=5,
            vad_filter=False,
            temperature=[0.0, 0.2, 0.4, 0.6],
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            condition_on_previous_text=False  # Prevent hallucination loops
        )
        raw_text = " ".join([segment.text for segment in segments]).strip()
        duration = info.duration
    else:
        # standard whisper
        result = model.transcribe(
            audio_path,
            fp16=False,
            initial_prompt=prompt,
            language="en",
            temperature=0.0,
            no_speech_threshold=0.6,
            logprob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            condition_on_previous_text=False  # Prevent hallucination loops
        )
        raw_text = result["text"].strip()
        duration = result.get("duration", 0)
    
    # Post-process
    corrected_text = post_process_transcription(raw_text, config)
    
    elapsed = time.time() - start_time
    
    return {
        'raw_text': raw_text,
        'corrected_text': corrected_text,
        'duration': duration,
        'transcription_time': elapsed
    }

# ============================================================================
# FILE HANDLING
# ============================================================================

def ensure_csv_exists(csv_path):
    """Create CSV with headers if it doesn't exist"""
    if not os.path.exists(csv_path):
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp',
                'filename',
                'raw_text',
                'corrected_text',
                'audio_duration',
                'transcription_time',
                'realtime_factor'
            ])

def append_to_csv(csv_path, filename, result):
    """Append transcription result to CSV"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    realtime_factor = result['transcription_time'] / result['duration'] if result['duration'] > 0 else 0
    
    with open(csv_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            timestamp,
            filename,
            result['raw_text'],
            result['corrected_text'],
            f"{result['duration']:.1f}",
            f"{result['transcription_time']:.1f}",
            f"{realtime_factor:.2f}"
        ])

def is_file_ready(filepath):
    """Check if file is completely written (size stable)"""
    try:
        size1 = os.path.getsize(filepath)
        time.sleep(0.5)
        size2 = os.path.getsize(filepath)
        return size1 == size2
    except (OSError, FileNotFoundError):
        return False

def get_new_audio_files(watch_folder, processed_folder):
    """Get list of new audio files that haven't been processed yet"""
    if not os.path.exists(watch_folder):
        return []
    
    # Get all audio files in watch folder
    audio_extensions = ('.mp3', '.wav', '.m4a', '.flac')
    watch_files = {
        f for f in os.listdir(watch_folder)
        if f.lower().endswith(audio_extensions)
    }
    
    # Get already processed files
    if os.path.exists(processed_folder):
        processed_files = set(os.listdir(processed_folder))
    else:
        processed_files = set()
    
    # Return files that haven't been processed
    return sorted(watch_files - processed_files)

def move_to_processed(source_path, filename, processed_folder):
    """Move file to processed folder"""
    os.makedirs(processed_folder, exist_ok=True)
    dest_path = os.path.join(processed_folder, filename)
    shutil.move(source_path, dest_path)

# ============================================================================
# MAIN PROCESSING LOOP
# ============================================================================

def process_file(model, filepath, filename, config):
    """Process a single audio file"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{timestamp}] Processing: {filename}")
    
    try:
        # Get prompt
        prompt = config.get("prompt_vocabulary", "")
        
        # Transcribe
        result = transcribe_audio(model, filepath, prompt, config)
        
        # Log results
        print(f"  Duration: {result['duration']:.1f}s | Transcription: {result['transcription_time']:.1f}s")
        print(f"  Text: {result['corrected_text'][:100]}{'...' if len(result['corrected_text']) > 100 else ''}")
        
        # Append to CSV
        append_to_csv(OUTPUT_CSV, filename, result)
        
        # Send Pushover notification if configured
        if PUSHOVER_AVAILABLE and config.get('pushover', {}).get('enabled', False):
            pushover_config = config.get('pushover', {})
            message = format_dispatch_message(
                result['corrected_text'],
                filename,
                result['transcription_time']
            )
            send_pushover("🚑 WRS Page", message, pushover_config)
        
        # Generate HTML view (for mobile access)
        try:
            import subprocess
            subprocess.run(['python3', 'generate_recent_calls.py'], 
                         capture_output=True, timeout=5)
        except:
            pass  # Don't fail if HTML generation fails
        
        # Move to processed
        move_to_processed(filepath, filename, PROCESSED_FOLDER)
        print(f"  ✓ Moved to {PROCESSED_FOLDER}/")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def watch_and_process(model, config):
    """Main loop - watch folder and process new files"""
    print("=" * 80)
    print("Dispatch Transcription Processor")
    print("=" * 80)
    print(f"Watch folder:     {WATCH_FOLDER}")
    print(f"Processed folder: {PROCESSED_FOLDER}")
    print(f"Output CSV:       {OUTPUT_CSV}")
    print(f"Config file:      {CONFIG_FILE}")
    print(f"Model:            {MODEL_SIZE}")
    print(f"Mode:             {'faster-whisper (Pi)' if USING_FASTER_WHISPER else 'standard whisper (Mac)'}")
    
    # Show Pushover status
    if PUSHOVER_AVAILABLE and config.get('pushover', {}).get('enabled', False):
        print(f"Pushover:         Enabled (priority: {config.get('pushover', {}).get('priority', 1)})")
    else:
        print(f"Pushover:         Disabled")
    
    print("=" * 80)
    print(f"\nCorrections loaded: {len(config.get('exact_corrections', {}))}")
    print(f"Place names loaded: {len(config.get('place_names', []))}")
    print(f"Strip headers:      {config.get('strip_dispatcher_headers', True)}")
    print("\nPress Ctrl+C to stop\n")
    print("=" * 80)
    
    # Ensure folders exist
    os.makedirs(WATCH_FOLDER, exist_ok=True)
    os.makedirs(PROCESSED_FOLDER, exist_ok=True)
    ensure_csv_exists(OUTPUT_CSV)
    
    processed_count = 0
    
    try:
        while True:
            # Get new files
            new_files = get_new_audio_files(WATCH_FOLDER, PROCESSED_FOLDER)
            
            if new_files:
                print(f"\nFound {len(new_files)} new file(s)")
                
                for filename in new_files:
                    filepath = os.path.join(WATCH_FOLDER, filename)
                    
                    # Wait for file to be completely written
                    if not is_file_ready(filepath):
                        print(f"  ⏳ Waiting for {filename} to finish recording...")
                        time.sleep(2)
                        if not is_file_ready(filepath):
                            print(f"  ⚠️  Skipping {filename} (still being written)")
                            continue
                    
                    # Process the file
                    if process_file(model, filepath, filename, config):
                        processed_count += 1
            
            # Wait before checking again
            time.sleep(CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n\n" + "=" * 80)
        print("Stopping processor...")
        print(f"Total files processed: {processed_count}")
        print("=" * 80)

# ============================================================================
# ENTRY POINT
# ============================================================================

def main(test_mode=False):
    # Load config
    config = load_config()

    if test_mode:
        print("⚡ Test mode: notifications will only go to Ben Truby")
        pushover = config.get('pushover', {})
        pushover['user_keys'] = [e for e in pushover.get('user_keys', []) if isinstance(e, dict) and e.get('name') == 'Ben Truby']
        config['pushover'] = pushover
    
    # Initialize model
    model = initialize_model()
    
    # Start watching and processing
    watch_and_process(model, config)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Only send notifications to Ben Truby')
    args = parser.parse_args()
    main(test_mode=args.test)