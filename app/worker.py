import os
import json
import base64
import tempfile
import ffmpeg
from celery import Celery
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import ConversionJob

celery_app = Celery("worker", broker="redis://redis:6379/0", backend="redis://redis:6379/0")

# Sync DB connection for Celery worker
DB_URL_SYNC = "postgresql://lottie_user:securepassword@db/lottie_db"
engine = create_engine(DB_URL_SYNC)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

MAX_JSON_SIZE = int(1.95 * 1024 * 1024)  # 1.95 MB
JSON_OVERHEAD = 25000
BASE64_FACTOR = 4 / 3


def _compress_frame(img, webp_path, budget_bytes, start_quality=88):
    quality = start_quality
    while True:
        img.save(webp_path, "WEBP", quality=quality, method=6)
        size = os.path.getsize(webp_path)
        if size <= budget_bytes or quality <= 20:
            return quality, size
        quality -= 5


@celery_app.task(bind=True)
def process_video_task(self, job_id: str, input_path: str):
    session = SessionLocal()
    job = session.query(ConversionJob).get(job_id)
    job.status = "PROCESSING"
    session.commit()

    try:
        output_path = f"/storage/outputs/{job_id}.json"

        with tempfile.TemporaryDirectory() as temp_dir:
            probe = ffmpeg.probe(input_path)
            video_info = next(s for s in probe["streams"] if s["codec_type"] == "video")
            width = int(video_info["width"])
            height = int(video_info["height"])

            max_dim = 560
            if width > max_dim or height > max_dim:
                ratio = min(max_dim / width, max_dim / height)
                width, height = int(width * ratio), int(height * ratio)

            fps = 12
            (
                ffmpeg
                .input(input_path)
                .output(
                    f"{temp_dir}/frame_%04d.png",
                    vf=f"fps={fps},scale={width}:{height}:flags=lanczos",
                )
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )

            frames = sorted(f for f in os.listdir(temp_dir) if f.endswith(".png"))
            num_frames = len(frames)
            if num_frames == 0:
                raise Exception("No frames extracted from video")

            budget_bytes_per_frame = int(
                (MAX_JSON_SIZE - JSON_OVERHEAD) / BASE64_FACTOR / num_frames
            )
            if budget_bytes_per_frame < 500:
                raise Exception("Video is too long to fit within the 1.95MB output limit")

            assets = []
            layers = []

            for idx, frame_file in enumerate(frames):
                img_path = os.path.join(temp_dir, frame_file)
                img = Image.open(img_path)
                webp_temp = os.path.join(temp_dir, f"opt_{idx}.webp")
                _compress_frame(img, webp_temp, budget_bytes_per_frame)

                with open(webp_temp, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode("utf-8")

                asset_id = f"image_{idx}"
                assets.append({
                    "id": asset_id,
                    "w": width,
                    "h": height,
                    "u": "",
                    "e": 1,
                    "p": f"data:image/webp;base64,{encoded_string}",
                })

                layers.append({
                    "ty": 2,
                    "nm": f"Frame {idx}",
                    "refId": asset_id,
                    "ks": {
                        "o": {"a": 0, "k": 100},
                        "r": {"a": 0, "k": 0},
                        "p": {"a": 0, "k": [width / 2, height / 2, 0]},
                        "a": {"a": 0, "k": [width / 2, height / 2, 0]},
                        "s": {"a": 0, "k": [100, 100, 100]},
                    },
                    "ip": idx,
                    "op": idx + 1,
                    "st": idx,
                    "bm": 0,
                })

            lottie_data = {
                "v": "5.5.2",
                "fr": fps,
                "ip": 0,
                "op": num_frames,
                "w": width,
                "h": height,
                "nm": "Converted Video",
                "ddd": 0,
                "assets": assets,
                "layers": layers,
            }

            with open(output_path, "w") as f:
                json.dump(lottie_data, f)

            final_size = os.path.getsize(output_path)
            if final_size > MAX_JSON_SIZE:
                raise Exception(
                    f"Failed to compress under 1.95MB. Final size: {final_size} bytes"
                )

            job.status = "COMPLETED"
            job.output_file_path = output_path
            job.output_size_bytes = final_size
            session.commit()

    except Exception as e:
        job.status = "FAILED"
        job.error_message = str(e)
        session.commit()
    finally:
        session.close()
