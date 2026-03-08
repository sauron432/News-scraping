@echo off
cd /d "D:\My files\practice\Mindrisers\Intern project\News scraping"

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    echo Installing packages...
    .venv\Scripts\pip install requests beautifulsoup4 selenium
)

echo Running scraper...
.venv\Scripts\python election_scraper.py
pause