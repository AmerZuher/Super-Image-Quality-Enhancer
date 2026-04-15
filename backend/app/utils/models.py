from pydantic import BaseModel

class ImageBase(BaseModel):
    original_path: str
    enhanced_path: str = None

class ImageCreate(ImageBase):
    pass

class Image(ImageBase):
    id: int
    created_at: str
    
    class Config:
        orm_mode = True