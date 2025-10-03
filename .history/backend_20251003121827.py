# backend.py - Enhanced version aligned with Arduino firmware
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
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
    print("Warning: GEMINI_API_KEY not found")
    GEMINI_API_KEY = "demo_key_placeholder"

# ----------------- FASTAPI SETUP -----------------
app = FastAPI(title="Vaultify Security Backend", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- DATA MODELS -----------------
class LogEntry(BaseModel):
    event: str
    detail: str
    timestamp: Optional[str] = None
    metadata: Optional[dict] = None

# Valid event types from Arduino
VALID_EVENTS = {
    "motion_alert",
    "alarm_deactivated", 
    "door_unlocked",
    "door_locked",
    "rfid_invalid",
    "door_autolock",
    "system_start"
}

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
    print("✅ AI models initialized")
except Exception as e:
    print(f"❌ AI initialization error: {e}")
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
@app.get("/")
def root():
    return {
        "message": "Vaultify Security Backend v2.0",
        "endpoints": {
            "logs": "/api/logs",
            "summary": "/api/summary",
            "ask": "/api/ask",
            "stats": "/api/stats",
            "health": "/api/health"
        }
    }

@app.post("/api/logs")
def add_log(entry: LogEntry):
    global vector_store
    
    # Validate event type
    if entry.event not in VALID_EVENTS:
        print(f"⚠️ Unknown event type: {entry.event}")
    
    # Add server timestamp if missing
    log_data = entry.dict()
    if not log_data.get('timestamp'):
        log_data['timestamp'] = datetime.now().isoformat()
    
    logs.append(log_data)
    print(f"📝 Log added: {entry.event} - {entry.detail}")
    
    # Update vector store incrementally
    if embeddings is not None:
        try:
            log_text = f"[{log_data['timestamp']}] {entry.event}: {entry.detail}"
            if entry.metadata:
                log_text += f" | Metadata: {entry.metadata}"
            
            chunks = text_splitter.split_text(log_text)
            
            if vector_store is None:
                vector_store = FAISS.from_texts(chunks, embeddings)
            else:
                vector_store.add_texts(chunks)
        except Exception as e:
            print(f"⚠️ Vector store update error: {e}")
    
    return {
        "message": "Log added successfully",
        "total_logs": len(logs),
        "event_type": entry.event
    }

@app.get("/api/logs")
def get_logs(limit: Optional[int] = None, event_type: Optional[str] = None):
    filtered_logs = logs
    
    # Filter by event type if specified
    if event_type:
        filtered_logs = [log for log in logs if log['event'] == event_type]
    
    # Limit results
    if limit:
        filtered_logs = filtered_logs[-limit:]
    
    return {
        "logs": filtered_logs,
        "total": len(logs),
        "filtered": len(filtered_logs)
    }

@app.get("/api/stats")
def get_statistics():
    """Get detailed statistics about security events"""
    if not logs:
        return {"message": "No logs available"}
    
    event_counts = {}
    recent_events = []
    critical_events = []
    
    for log in logs:
        event_type = log['event']
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
        
        # Track critical events
        if event_type in ['motion_alert', 'rfid_invalid']:
            critical_events.append(log)
    
    # Get last 5 events
    recent_events = logs[-5:]
    
    return {
        "total_events": len(logs),
        "event_breakdown": event_counts,
        "critical_events_count": len(critical_events),
        "recent_events": recent_events,
        "first_event": logs[0].get('timestamp', 'Unknown'),
        "last_event": logs[-1].get('timestamp', 'Unknown')
    }

@app.get("/api/summary")
def summarize_logs():
    if not logs:
        return {"summary": "No security events logged yet."}
    
    if llm is None:
        # Fallback summary
        event_counts = {}
        for log in logs:
            event_counts[log['event']] = event_counts.get(log['event'], 0) + 1
        
        summary = "📊 Security Events Summary:\n\n"
        for event, count in event_counts.items():
            summary += f"• {event.replace('_', ' ').title()}: {count} occurrence(s)\n"
        
        return {"summary": summary}
    
    try:
        if vector_store is None:
            logs_text = "\n".join([
                f"[{log.get('timestamp', 'N/A')}] {log['event']}: {log['detail']}"
                for log in logs
            ])
            prompt = f"""Analyze these security system events and provide a concise summary:

{logs_text}

Provide:
1. Overview of activity
2. Notable security concerns
3. System status assessment

Summary:"""
            summary = llm.invoke(prompt).content
        else:
            chain = load_qa_chain(llm, chain_type="stuff")
            docs = vector_store.similarity_search("Summarize all security events with focus on threats", k=10)
            summary = chain.run(
                input_documents=docs,
                question="Provide a comprehensive security summary highlighting any concerns"
            )
        
        return {"summary": summary}
    except Exception as e:
        print(f"❌ Summary generation error: {e}")
        return {"summary": f"Error: {str(e)}"}

@app.get("/api/ask")
def ask_ai(question: str):
    if not logs:
        return {"answer": "No security events have been logged yet."}
    
    if not question:
        raise HTTPException(status_code=400, detail="Question parameter required")
    
    if llm is None:
        # Enhanced fallback with metadata support
        question_lower = question.lower()
        event_counts = {}
        
        for log in logs:
            event_counts[log['event']] = event_counts.get(log['event'], 0) + 1
        
        # Smart pattern matching
        if "door" in question_lower:
            unlocks = event_counts.get('door_unlocked', 0)
            locks = event_counts.get('door_locked', 0)
            autolocks = event_counts.get('door_autolock', 0)
            return {"answer": f"Door activity: {unlocks} manual unlocks, {locks} manual locks, {autolocks} auto-locks"}
        
        if "motion" in question_lower or "theft" in question_lower:
            alerts = event_counts.get('motion_alert', 0)
            deactivations = event_counts.get('alarm_deactivated', 0)
            return {"answer": f"Motion detection: {alerts} alerts triggered, {deactivations} alarms deactivated"}
        
        if "rfid" in question_lower or "card" in question_lower:
            invalid = event_counts.get('rfid_invalid', 0)
            return {"answer": f"RFID activity: {invalid} unauthorized card attempts detected"}
        
        # Default comprehensive answer
        total = len(logs)
        recent = logs[-3:]
        recent_text = "\n".join([f"• {log['event']}: {log['detail']}" for log in recent])
        
        return {"answer": f"Total events: {total}\n\nRecent activity:\n{recent_text}\n\nEvent summary: {event_counts}"}
    
    try:
        if vector_store is None:
            logs_context = "\n".join([
                f"[{log.get('timestamp', 'N/A')}] {log['event']}: {log['detail']}"
                + (f" | Metadata: {log['metadata']}" if log.get('metadata') else "")
                for log in logs
            ])
            prompt = f"""You are analyzing security system logs. Answer the question based on this data:

{logs_context}

Question: {question}

Provide a clear, specific answer:"""
            answer = llm.invoke(prompt).content
        else:
            chain = load_qa_chain(llm, chain_type="stuff")
            docs = vector_store.similarity_search(question, k=8)
            answer = chain.run(input_documents=docs, question=question)
        
        return {"answer": answer}
    except Exception as e:
        print(f"❌ Q&A error: {e}")
        return {"answer": f"Error processing question: {str(e)}"}

@app.delete("/api/logs")
def clear_logs():
    """Clear all logs (use with caution)"""
    global logs, vector_store
    logs = []
    vector_store = None
    return {"message": "All logs cleared"}

@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "logs_count": len(logs),
        "ai_enabled": llm is not None,
        "vector_store_active": vector_store is not None
    }

# ----------------- RUN SERVER -----------------
if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Vaultify Security Backend v2.0...")
    print("📊 Access dashboard at: http://localhost:8000")
    print("📖 API docs at: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)