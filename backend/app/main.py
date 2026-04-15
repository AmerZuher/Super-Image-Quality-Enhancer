from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import shutil
import os
import uuid
from utils.database import get_db_connection
from utils.enhance import enhance_image_func
from utils.init_db import init_database 
from psycopg2.extras import RealDictCursor
import uvicorn

app = FastAPI(title="Image Processing API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create images directory if it doesn't exist
os.makedirs("images", exist_ok=True)

# Mount the images directory to serve static files
app.mount("/images", StaticFiles(directory="images"), name="images")

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_database()

@app.post("/upload/")
async def upload_image(file: UploadFile = File(...)):
    # Generate a unique filename
    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"original_{uuid.uuid4()}{file_extension}"
    file_path = os.path.join("images", unique_filename)
    
    # Save the file
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Save file path to database
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute(
        "INSERT INTO images (original_path) VALUES (%s) RETURNING id, original_path",
        (file_path,)
    )
    
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return {
        "id": result["id"],
        "original_path": result["original_path"],
        "original_url": f"/images/{unique_filename}"
    }

@app.post("/enhance/{image_id}")
async def enhance_image(image_id: int):
    return await enhance_image_func(image_id)

@app.get("/images/")
async def get_all_images():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("SELECT * FROM images ORDER BY created_at DESC")
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    
    # Add URLs for frontend
    for result in results:
        if result["original_path"]:
            result["original_url"] = f"/images/{os.path.basename(result['original_path'])}"
        if result["enhanced_path"]:
            result["enhanced_url"] = f"/images/{os.path.basename(result['enhanced_path'])}"
    
    return results

@app.get("/images/{image_id}")
async def get_image(image_id: int):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute(
        "SELECT * FROM images WHERE id = %s",
        (image_id,)
    )
    
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not result:
        raise HTTPException(status_code=404, detail="Image not found")
    
    # Add URLs for frontend
    if result["original_path"]:
        result["original_url"] = f"/images/{os.path.basename(result['original_path'])}"
    if result["enhanced_path"]:
        result["enhanced_url"] = f"/images/{os.path.basename(result['enhanced_path'])}"
    
    return result

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)