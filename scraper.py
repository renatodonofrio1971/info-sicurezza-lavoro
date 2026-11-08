name: Scraper Notturno Info Sicurezza

on:
  schedule:
    - cron: '0 2 * * *'
  workflow_dispatch: 

jobs:
  run-scraper:
    runs-on: ubuntu-latest

    steps:
    - name: Accedi al codice del repository
      uses: actions/checkout@v4

    - name: Configura Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.10'

    - name: Installa le librerie necessarie
      run: |
        python -m pip install --upgrade pip
        pip install requests beautifulsoup4 pandas

    - name: Esegui lo Scraper ed invia a Glide
      env:
        GLIDE_APP_ID: ${{ secrets.GLIDE_APP_ID }}
        GLIDE_API_TOKEN: ${{ secrets.GLIDE_API_TOKEN }}
      run: python scraper.py
