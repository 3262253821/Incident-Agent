$env:PYTHONPATH = 'E:\IncidentAgent'
Set-Location -LiteralPath 'E:\IncidentAgent'
py -m uvicorn app.main:app --host 127.0.0.1 --port 8001
