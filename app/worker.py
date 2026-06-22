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

MAX_JSON_SIZE = 1.6 * 1024 * 1024  # 1.6 MB in bytes

@celery_app.task(bind=True)
def process_video_task(self, job_id: str, input_path: str):
    session = SessionLocal()
    job = session.query(ConversionJob).get(job_id)
    job.status = "PROCESSING"
    session.commit()

    try:
        output_path = f"/storage/outputs/{job_id}.json"
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # 1. Probe video to get duration
            probe = ffmpeg.probe(input_path)
            video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            width = int(video_info['width'])
            height = int(video_info['height'])
            
            # Scale down to reasonable bounds for a Lottie file to save space
            max_dim = 480
            if width > max_dim or height > max_dim:
                ratio = min(max_dim/width, max_dim/height)
                width, height = int(width * ratio), int(height * ratio)

            # 2. Extract frames at 10 FPS to save space
            fps = 10
            ffmpeg.input(input_path).output(
                f'{temp_dir}/frame_%04d.png', 
                vf=f'fps={fps},scale={width}:{height}'
            ).run(capture_stdout=True, capture_stderr=True)

            frames = sorted([f for f in os.listdir(temp_dir) if f.endswith('.png')])
            num_frames = len(frames)

            # 3. Size Budgeting constraint calculation
            # Base64 inflates size by ~33%. JSON structure adds ~20KB overhead.
            # (1.6MB - 20KB) / 1.33 = ~1.18MB available for raw WebP images
            budget_bytes_per_frame = int((MAX_JSON_SIZE - 20000) / 1.33 / num_frames)
            
            assets = []
            layers = []

            # 4. Process frames
            for idx, frame_file in enumerate(frames):
                img_path = os.path.join(temp_dir, frame_file)
                img = Image.open(img_path)
                
                # Compress to WebP iteratively to hit the budget
                quality = 80
                webp_temp = os.path.join(temp_dir, f"opt_{idx}.webp")
                
                while True:
                    img.save(webp_temp, 'WEBP', quality=quality)
                    size = os.path.getsize(webp_temp)
                    if size <= budget_bytes_per_frame or quality <= 10:
                        break
                    quality -= 10 # Drop quality until it fits the budget

                # Convert to base64
                with open(webp_temp, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

                asset_id = f"image_{idx}"
                assets.append({
                    "id": asset_id,
                    "w": width, "h": height,
                    "u": "", "p": f"data:image/webp;base64,{encoded_string}"
                })

                # Create layer for this frame (Show only for its specific frame duration)
                layers.append({
                    "ty": 2, "nm": f"Frame {idx}", "refId": asset_id,
                    "ks": {"o": {"a": 0, "k": 100}, "r": {"a": 0, "k": 0}, "p": {"a": 0, "k": [width/2, height/2, 0]}, "a": {"a": 0, "k": [width/2, height/2, 0]}, "s": {"a": 0, "k": [100, 100, 100]}},
                    "ip": idx, "op": idx + 1, "st": idx, "bm": 0
                })

            # 5. Construct Lottie JSON
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
                "layers": layers
            }

            # 6. Save and verify size
            with open(output_path, "w") as f:
                json.dump(lottie_data, f)
            
            final_size = os.path.getsize(output_path)
            if final_size > MAX_JSON_SIZE:
                 # Fallback: if we somehow missed the target, throw an error to be handled
                 raise Exception(f"Failed to compress under 1.6MB. Final size: {final_size}")

            # 7. Update DB on Success
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
