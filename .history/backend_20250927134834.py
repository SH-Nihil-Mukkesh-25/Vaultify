# backend.py
from fastapi import FastAPI
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain.chains.question_answering import load_qa_chain
from langchain.vectorstores import FAISS
from dotenv import load_dotenv
import os

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

app = FastAPI(title="Vaultify AI Backend")

# -------------------- LLM + Embeddings --------------------
llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    google_api_key=GEMINI_API_KEY
)

embeddings = GoogleGenerativeAIEmbeddings(
    model="models/embedding-001",
    google_api_key=GEMINI_API_KEY
)

# -------------------- In-Memory Logs + Vector Store --------------------
logs = []
vector_store = None

class EventLog(BaseModel):
    event: str
    detail: str

# -------------------- Endpoints --------------------
@app.post("/api/logs")
def receive_log(item: EventLog):
    logs.append(f"{item.event}: {item.detail}")
    global vector_store
    if vector_store is None:
        vector_store = FAISS.from_texts(logs, embeddings)
    else:
        vector_store.add_texts([f"{item.event}: {item.detail}"])
    return {"status": "ok"}

@app.get("/api/logs")
def get_logs():
    return logs

@app.get("/api/summary")
def get_summary():
    if not logs:
        return {"summary": "No events logged yet."}
    # Prepare documents for QA chain
    docs = [{"page_content": l} for l in logs]
    chain = load_qa_chain(llm, chain_type="stuff")
    prompt = "Summarize the security events for today."
    summary = chain.run(input_documents=docs, question=prompt)
    return {"summary": summary}

@app.get("/api/ask")
def ask_question(q: str):
    if not vector_store:
        return {"answer": "No logs available yet."}
    results = vector_store.similarity_search(q)
    chain = load_qa_chain(llm, chain_type="stuff")
    answer = chain.run(input_documents=results, question=q)
    return {"answer": answer}
