@echo off
if not defined VIRTUAL_ENV (
    call venv\Scripts\activate.bat
)
uvicorn app.main:app --reload