import asyncio
import json
from typing import List, Dict

class InterviewerService:
    @staticmethod
    async def get_response_stream(chat_history: List[Dict[str, str]]):
        # Filter for user messages to gauge the progress of the session
        user_messages = [m for m in chat_history if m.get("role") == "user"]
        turn_count = len(user_messages)

        # Socratic questions tailored to different stages of a system design interview
        if turn_count <= 1:
            full_response = (
                "Welcome! Let's work on this system design question. "
                "Before jumping into drawing schemas or diagrams, let's clarify the scope. "
                "What do you think are the core functional requirements we must implement, "
                "and what non-functional requirements (such as latency, availability, consistency) should we target?"
            )
        elif turn_count == 2:
            full_response = (
                "Those requirements are solid. Now, let's do some quick back-of-the-envelope estimation. "
                "Based on the constraints given, how much write/read throughput (QPS) do you estimate we'll need, "
                "and how much storage will we need to persist over 5 years?"
            )
        elif turn_count == 3:
            full_response = (
                "Makes sense. Let's design the high-level API interfaces. "
                "What REST/gRPC endpoints would you expose, and what payload parameters do they require?"
            )
        elif turn_count == 4:
            full_response = (
                "Good API design. Let's design the data storage layer. "
                "What database schemas or models would you define? Also, would you prefer SQL or NoSQL "
                "for this use case, and why?"
            )
        else:
            full_response = (
                "That data schema looks clean. To finalize, how would you scale this system to handle bottlenecks? "
                "Where would you introduce caches, load balancers, CDN, or database replication/sharding?"
            )

        # Stream response back word by word using Server-Sent Events (SSE) formatting
        words = full_response.split(" ")
        for i, word in enumerate(words):
            chunk = word if i == 0 else " " + word
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            await asyncio.sleep(0.04)  # Simulate typing/network latency
        
        # Send a terminal signal indicating the stream is complete
        yield "data: [DONE]\n\n"
