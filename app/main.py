import os
import shutil
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from .models import Base, ConversionJob
from .worker import process_video_task
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="Video to Lottie API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000","https://durable-assignment-overall-bracelet.trycloudflare.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DB Setup
DATABASE_URL = "postgresql+asyncpg://lottie_user:securepassword@db/lottie_db"
engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

os.makedirs("/storage/inputs", exist_ok=True)
os.makedirs("/storage/outputs", exist_ok=True)
# 2. Serve the outputs directory publicly so the frontend can download the Lottie files
app.mount("/outputs", StaticFiles(directory="/storage/outputs"), name="outputs")

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.post("/convert/")
async def convert_video(file: UploadFile = File(...)):
    if not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="File must be a video.")

    # Save input file
    input_path = f"/storage/inputs/{file.filename}"
    with open(input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Create DB Record
    async with AsyncSessionLocal() as session:
        job = ConversionJob(input_file_path=input_path)
        session.add(job)
        await session.commit()
        await session.refresh(job)

    # Trigger Celery Task
    process_video_task.delay(str(job.id), input_path)

    return {"job_id": job.id, "message": "Video is processing. Check status via /status/{job_id}"}

@app.get("/download/{job_id}")
async def download_lottie(job_id: str):
    file_path = f"/storage/outputs/{job_id}.json"
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found or not ready yet.")
    
    # Returning a FileResponse automatically handles chunked downloading 
    # and we can force the 'attachment' header to trigger a true download.
    return FileResponse(
        path=file_path, 
        filename=f"lottie_animation.json", # This is the name the user will see when saving
        media_type="application/json",
        headers={"Content-Disposition": "attachment"} # This forces the download prompt
    )

@app.get("/status/{job_id}")
async def get_status(job_id: str):
    async with AsyncSessionLocal() as session:
        job = await session.get(ConversionJob, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"status": job.status, "output_url": job.output_file_path, "size": job.output_size_bytes}
