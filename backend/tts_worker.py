"""Isolated, lazy Piper CPU worker. JSON lines in/out; no browser/system voices."""
from __future__ import annotations

import json
import os
import sys
import time
import wave
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")


def main() -> None:
    # Windows redirected streams otherwise inherit a legacy codepage.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    # Keep third-party diagnostic output off the JSON protocol channel.
    protocol = sys.stdout
    sys.stdout = sys.stderr
    voice = None
    loaded_model = None
    for line in sys.stdin:
        request_id = None
        try:
            req = json.loads(line)
            request_id = req.get("id")
            if req.get("op") == "exit":
                break
            started = time.perf_counter()
            from piper import PiperVoice, SynthesisConfig
            from piper.config import PiperConfig
            from piper.phonemize_espeak import ESPEAK_DATA_DIR
            import onnxruntime

            model = str(Path(req["model"]).resolve())
            if voice is None or model != loaded_model:
                # Keep one model resident when switching among installed voices.
                voice = None
                loaded_model = None
                # Bound inference threads so a large desktop CPU does not spend
                # every core on a short paragraph while the reader is in use.
                session_options = onnxruntime.SessionOptions()
                session_options.intra_op_num_threads = 2
                session_options.inter_op_num_threads = 1
                with open(model + ".json", encoding="utf-8") as config_file:
                    config = PiperConfig.from_dict(json.load(config_file))
                voice = PiperVoice(
                    session=onnxruntime.InferenceSession(model, sess_options=session_options, providers=["CPUExecutionProvider"]),
                    config=config,
                    # eSpeak uses narrow paths on Windows; keep the data path ASCII relative to the app.
                    espeak_data_dir=Path(os.path.relpath(ESPEAK_DATA_DIR, Path.cwd())), 
                )
                loaded_model = model
            destination = Path(req["output"])
            temporary = destination.with_suffix(".part.wav")
            try:
                with wave.open(str(temporary), "wb") as audio:
                    voice.synthesize_wav(
                        req["text"],
                        audio,
                        syn_config=SynthesisConfig(length_scale=1.0 / float(req["rate"])),
                    )
                with wave.open(str(temporary), "rb") as audio:
                    result = {
                        "id": request_id,
                        "ok": True,
                        "duration": audio.getnframes() / audio.getframerate(),
                        "sample_rate": audio.getframerate(),
                        "channels": audio.getnchannels(),
                        "seconds": round(time.perf_counter() - started, 3),
                    }
                if result["duration"] <= 0:
                    raise RuntimeError("Синтез не создал звук")
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
            protocol.write(json.dumps(result, ensure_ascii=False) + "\n")
            protocol.flush()
        except Exception as exc:
            protocol.write(json.dumps({"id": request_id, "ok": False, "error": str(exc)}, ensure_ascii=False) + "\n")
            protocol.flush()


if __name__ == "__main__":
    main()
