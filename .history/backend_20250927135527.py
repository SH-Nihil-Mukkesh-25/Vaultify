# backend.py
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain.chains.question_answering import load_qa_chain
import os
from dotenv import load_dotenv

# ----------------- ENVIRONMENT -----------------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ----------------- FASTAPI SETUP -----------------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow frontend connections
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- DATA MODELS -----------------
class LogEntry(BaseModel):
    event: str
    detail: str

logs: List[dict] = []  # stores all logs

# ----------------- LLM & Embeddings -----------------
llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    temperature=0,
    max_tokens=512,
    google_api_key=GEMINI_API_KEY
)

embeddings = GoogleGenerativeAIEmbeddings(
    model="models/embedding-001",
    google_api_key=GEMINI_API_KEY
)

vector_store = None
text_splitter = RecursiveCharacterTextSplitter(
    separators="\n",
    chunk_size=1000,
    chunk_overlap=150,
    length_function=len
)

# ----------------- API ENDPOINTS -----------------

@app.post("/api/logs")
def add_log(entry: LogEntry):
    global vector_store
    logs.append(entry.dict())
    # Update vector store
    all_texts = [f"{log['event']}: {log['detail']}" for log in logs]
    chunks = text_splitter.split_text("\n".join(all_texts))
    vector_store = FAISS.from_texts(chunks, embeddings)
    return {"message": "Log added", "total_logs": len(logs)}

@app.get("/api/logs")
def get_logs():
    return {"logs": logs}

@app.get("/api/summary")
def summarize_logs():
    if not logs or vector_store is None:
        return {"summary": "No logs available yet."}
    # Use LLM to summarize logs
    chain = load_qa_chain(llm, chain_type="stuff")
    input_docs = vector_store.similarity_search("Summarize all security events", k=5)
    summary = chain.run(input_documents=input_docs, question="Summarize all security events")
    return {"summary": summary}

@app.get("/api/ask")
def ask_ai(question: str):
    if not logs or vector_store is None:
        return {"answer": "No logs available yet."}
    chain = load_qa_chain(llm, chain_type="stuff")
    input_docs = vector_store.similarity_search(question, k=5)
    answer = chain.run(input_documents=input_docs, question=question)
    return {"answer": answer}

# ----------------- HEALTH CHECK -----------------
@app.get("/api/health")
def health():
    return {"status": "Vaultify backend running!"}
