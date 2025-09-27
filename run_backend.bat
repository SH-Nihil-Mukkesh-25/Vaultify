@echo off
echo Setting up Vaultify Security Dashboard...
echo.
echo Please enter your Gemini API key:
set /p GEMINI_API_KEY="API Key: "
echo.
echo Starting backend with API key...
python backend.py
pause
