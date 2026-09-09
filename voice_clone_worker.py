import sys
import os
import argparse
import pysrt
from pydub import AudioSegment
from TTS.api import TTS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", required=True, help="Đường dẫn file mẫu giọng nói")
    parser.add_argument("--srt", required=True, help="Đường dẫn file SRT cần đọc")
    parser.add_argument("--lang", required=True, help="Mã ngôn ngữ (vi, en, ja...)")
    parser.add_argument("--output", required=True, help="Đường dẫn file audio xuất ra")
    args = parser.parse_args()

    print("LOADING_MODEL", flush=True)
    model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cuda")

    os.makedirs("temp_audio", exist_ok=True)

    subs = pysrt.open(args.srt, encoding="utf-8")
    final_audio = AudioSegment.silent(duration=0, frame_rate=24000)
    current_time_ms = 0
    total_lines = len(subs)

    for idx, sub in enumerate(subs):
        text_clean = sub.text.replace("\n", " ").strip()
        start_ms = (sub.start.hours * 3600 + sub.start.minutes * 60 + sub.start.seconds) * 1000 + sub.start.milliseconds

        if text_clean:
            print(f"PROGRESS {idx+1}/{total_lines}: {text_clean[:30]}", flush=True)
            temp_seg_path = f"temp_audio/clone_seg_{idx}.wav"
            try:
                model.tts_to_file(
                    text=text_clean,
                    speaker_wav=args.sample,
                    language=args.lang,
                    file_path=temp_seg_path
                )
                seg_audio = AudioSegment.from_file(temp_seg_path)
                seg_audio = seg_audio.set_frame_rate(24000).set_channels(1).set_sample_width(2)

                if start_ms > current_time_ms:
                    final_audio += AudioSegment.silent(duration=start_ms - current_time_ms, frame_rate=24000)
                    current_time_ms = start_ms

                final_audio += seg_audio
                current_time_ms += len(seg_audio)

                os.remove(temp_seg_path)
            except Exception as e:
                print(f"WARNING Bỏ qua câu {idx+1}: {e}", flush=True)

    final_audio.export(args.output, format="wav")
    print("DONE", flush=True)


if __name__ == "__main__":
    main()