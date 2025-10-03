# backend.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
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

if not GEMINI_API_KEY:
    print("Warning: GEMINI_API_KEY not found. Please set it in your environment or .env file")
    GEMINI_API_KEY = "demo_key_placeholder"

# ----------------- FASTAPI SETUP -----------------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "vaultify-ydgu-git-master-mukkeshnihil-gmailcoms-projects.vercel.app",
        "*"  # Allow all origins for IoT devices, or restrict as needed
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- ROOT ROUTE -----------------
@app.get("/")
def root():
    return {"message": "Vaultify backend is live! Visit /api/health for health check."}

# ----------------- DATA MODELS -----------------
class LogEntry(BaseModel):
    event: str
    detail: str

logs: List[dict] = []

# ----------------- LLM & Embeddings -----------------
try:
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
    print("✅ AI models initialized successfully")
except Exception as e:
    print(f"❌ Error initializing AI models: {e}")
    print("Using demo mode - AI features will return placeholder responses")
    llm = None
    embeddings = None

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
    
    if embeddings is not None:
        try:
            all_texts = [f"{log['event']}: {log['detail']}" for log in logs]
            chunks = text_splitter.split_text("\n".join(all_texts))
            vector_store = FAISS.from_texts(chunks, embeddings)
        except Exception as e:
            print(f"Error updating vector store: {e}")
    
    return {"message": "Log added", "total_logs": len(logs)}

@app.get("/api/logs")
def get_logs():
    return {"logs": logs}

@app.get("/api/summary")
def summarize_logs():
    if not logs:
        return {"summary": "No logs available yet."}
    
    if llm is None:
        event_counts = {}
        for log in logs:
            event_counts[log['event']] = event_counts.get(log['event'], 0) + 1
        summary = "Security Events Summary:\n"
        for event, count in event_counts.items():
            summary += f"- {event}: {count} occurrence(s)\n"
        return {"summary": summary}
    
    try:
        if vector_store is None:
            logs_text = "\n".join([f"- {log['event']}: {log['detail']}" for log in logs])
            prompt = f"Please provide a concise summary of these security events:\n{logs_text}\n\nSummary:"
            summary = llm.invoke(prompt).content
            return {"summary": summary}
        else:
            chain = load_qa_chain(llm, chain_type="stuff")
            input_docs = vector_store.similarity_search("Summarize all security events", k=5)
            summary = chain.run(input_documents=input_docs, question="Summarize all security events")
            return {"summary": summary}
    except Exception as e:
        print(f"Error generating AI summary: {e}")
        return {"summary": f"Error generating summary: {str(e)}"}

@app.get("/api/ask")
def ask_ai(question: str):
    if not logs:
        return {"answer": "No logs available yet."}
    
    if llm is None:
        question_lower = question.lower()
        event_counts = {}
        for log in logs:
            event_counts[log['event']] = event_counts.get(log['event'], 0) + 1
        
        if "door" in question_lower and "unlock" in question_lower:
            count = event_counts.get('door_unlocked', 0)
            return {"answer": f"The door has been unlocked {count} times based on the current logs."}
        elif "motion" in question_lower:
            count = event_counts.get('motion_alert', 0)
            return {"answer": f"There have been {count} motion alerts detected."}
        elif "rfid" in question_lower or "invalid" in question_lower:
            count = event_counts.get('rfid_invalid', 0)
            return {"answer": f"{count} invalid RFID card scans have been detected."}
        elif "autolock" in question_lower:
            count = event_counts.get('door_autolock', 0)
            return {"answer": f"The door has auto-locked {count} times."}
        elif "summary" in question_lower or "overview" in question_lower:
            summary = "Security Events Summary:\n"
            for event, count in event_counts.items():
                summary += f"• {event.replace('_', ' ').title()}: {count} occurrence(s)\n"
            return {"answer": summary}
        else:
            total_events = len(logs)
            recent_events = logs[-3:] if len(logs) >= 3 else logs
            recent_summary = "\n".join([f"• {log['event']}: {log['detail']}" for log in recent_events])
            return {"answer": f"You asked '{question}'. \n\nTotal events logged: {total_events}\nRecent events:\n{recent_summary}\n\nThis is a basic analysis. For more detailed insights, the AI can provide deeper analysis."}
    
    try:
        if vector_store is None:
            logs_text = "\n".join([f"- {log['event']}: {log['detail']}" for log in logs])
            prompt = f"Based on these security logs:\n{logs_text}\n\nQuestion: {question}\n\nPlease provide a helpful analysis:"
            answer = llm.invoke(prompt).content
            return {"answer": answer}
        else:
            chain = load_qa_chain(llm, chain_type="stuff")
            input_docs = vector_store.similarity_search(question, k=5)
            answer = chain.run(input_documents=input_docs, question=question)
            return {"answer": answer}
    except Exception as e:
        print(f"Error generating AI answer: {e}")
        return {"answer": f"Error generating answer: {str(e)}"}

# ----------------- HEALTH CHECK -----------------
@app.get("/api/health")
def health():
    return {"status": "Vaultify backend running!"}

# ----------------- RUN SERVER -----------------
if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Vaultify Security Dashboard Backend...")
    print("📊 Dashboard will be available at: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)