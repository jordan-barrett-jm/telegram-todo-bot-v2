from fastapi import FastAPI, HTTPException, Depends, Query, Header
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, declarative_base
import time

app = FastAPI()

DATABASE_URL = "sqlite:///./tasks.db"

engine = create_engine(DATABASE_URL, pool_size=100, max_overflow=0)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(String, index=True) 
    title = Column(String, index=True)
    description = Column(String, index=True, nullable=True)
    completed = Column(Boolean, default=False)


Base.metadata.create_all(bind=engine)

class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    completed: Optional[bool] = False

class TaskCreate(TaskBase):
    pass

class TaskUpdate(TaskBase):
    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None

class TaskInDB(TaskBase):
    id: int

    class Config:
        orm_mode = True

def get_db(chat_id: str = Header(...)):
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
@app.get("/api/tasks", response_model=List[TaskInDB])
def get_tasks(
    completed: Optional[bool] = Query(None, description="Filter tasks by completion status"),
    db: Session = Depends(get_db),
    chat_id: str = Header(...)
):
    query = db.query(Task).filter(Task.chat_id == chat_id)  # Filter by chat_id
    if completed is not None:
        query = query.filter(Task.completed == completed)
    return query.all()

@app.get("/api/tasks/{task_id}", response_model=TaskInDB)
def get_task(task_id: int, db: Session = Depends(get_db), chat_id: str = Header(...)):
    task = db.query(Task).filter(Task.id == task_id, Task.chat_id == chat_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@app.post("/api/tasks", response_model=TaskInDB)
def create_task(task: TaskCreate, db: Session = Depends(get_db), chat_id: str = Header(...)):
    db_task = Task(chat_id=chat_id, title=task.title, description=task.description, completed=task.completed)
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task

@app.put("/api/tasks/{task_id}", response_model=TaskInDB)
def update_task(task_id: int, updated_task: TaskUpdate, db: Session = Depends(get_db), chat_id: str = Header(...)):
    task = db.query(Task).filter(Task.id == task_id, Task.chat_id == chat_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if updated_task.title is not None:
        task.title = updated_task.title
    if updated_task.description is not None:
        task.description = updated_task.description
    if updated_task.completed is not None:
        task.completed = updated_task.completed
    
    db.commit()
    db.refresh(task)
    return task

@app.delete("/api/tasks/{task_id}", response_model=TaskInDB)
def delete_task(task_id: int, db: Session = Depends(get_db), chat_id: str = Header(...)):
    task = db.query(Task).filter(Task.id == task_id, Task.chat_id == chat_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    
    db.delete(task)
    db.commit()
    return task

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8445)
