Set-Location -LiteralPath 'E:\RagKnowledgeSystem'
py -m uvicorn app.main:app --reload --app-dir backend --host 127.0.0.1 --port 8000
