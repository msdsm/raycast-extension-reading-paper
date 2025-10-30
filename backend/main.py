import os
import asyncio
import json
import logging
from typing import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from anthropic import Anthropic
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Logging configuration
log_file_path = Path(__file__).parent / 'backend.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file_path)
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()

class TextRequest(BaseModel):
    text: str

class MCPClient:
    def __init__(self):
        self.session = None
        self.server_task = None
        self.session_ready = None
        self.anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    async def start_mcp_server(self):
        """Start MCP server and initialize session"""
        logger.info("Starting MCP server...")
        
        # Event to notify session initialization completion
        self.session_ready = asyncio.Event()
        
        # Configure MCP server parameters
        script_path = Path(__file__).parent / "mcp_server.py"
        server_params = StdioServerParameters(
            command="python",
            args=[str(script_path)],
            env=None
        )
        
        # Start server as a background task using stdio_client
        self.server_task = asyncio.create_task(self._run_server(server_params))
        
        # Wait until session is initialized
        try:
            await asyncio.wait_for(self.session_ready.wait(), timeout=10.0)
            logger.info("MCP server started successfully")
        except asyncio.TimeoutError:
            logger.error("MCP server failed to start within 10 seconds")
            if self.server_task:
                self.server_task.cancel()
            raise RuntimeError("Failed to start MCP server")
    
    async def _run_server(self, server_params: StdioServerParameters):
        """Establish communication with MCP server"""
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    self.session = session
                    await session.initialize()
                    logger.info("MCP session initialized")
                    
                    # Notify session initialization completion
                    self.session_ready.set()
                    
                    # Maintain session
                    try:
                        while True:
                            await asyncio.sleep(1)
                    except asyncio.CancelledError:
                        logger.info("MCP session cancelled")
                        raise
        except Exception as e:
            logger.error("Error in MCP server: %s", str(e), exc_info=True)
            raise
    
    async def stop_mcp_server(self):
        """Stop MCP server"""
        logger.info("Stopping MCP server...")
        if self.server_task:
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass
        self.session = None
        self.session_ready = None
        logger.info("MCP server stopped")
    
    async def _run_agent_loop(self, messages: list, claude_tools: list) -> AsyncGenerator[dict, None]:
        """Claude agent loop: automatically handle tool calls"""
        max_iterations = 10  # Prevent infinite loops
        
        for iteration in range(max_iterations):
            logger.info("Agent loop iteration %d", iteration + 1)
            
            # Call Claude (synchronous method)
            response = self.anthropic_client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=2048,
                tools=claude_tools,
                messages=messages
            )
            
            # Add response to message history
            assistant_content = []
            tool_uses = []
            
            for content_block in response.content:
                if content_block.type == "text":
                    # Return text response
                    yield {
                        "type": "text",
                        "content": content_block.text
                    }
                    assistant_content.append(content_block)
                elif content_block.type == "tool_use":
                    # Record tool use
                    tool_uses.append(content_block)
                    assistant_content.append(content_block)
                    yield {
                        "type": "tool_use",
                        "tool_name": content_block.name,
                        "tool_input": content_block.input
                    }
            
            # Add assistant response to history
            messages.append({
                "role": "assistant",
                "content": assistant_content
            })
            
            # If no tool calls, we're done
            if not tool_uses:
                logger.info("No tool use, agent loop complete")
                break
            
            # Execute tools on MCP server
            tool_results = []
            for tool_use in tool_uses:
                logger.info("Executing MCP tool: %s", tool_use.name)
                
                # Request MCP server to execute tool
                mcp_result = await self.session.call_tool(
                    tool_use.name,
                    tool_use.input
                )
                
                # Get tool result
                result_text = ""
                for content in mcp_result.content:
                    if hasattr(content, 'text'):
                        result_text += content.text
                
                logger.info("MCP tool result: %s", result_text)
                
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text
                })
                
                yield {
                    "type": "tool_result",
                    "tool_name": tool_use.name,
                    "content": result_text
                }
            
            # Add tool results to message history
            messages.append({
                "role": "user",
                "content": tool_results
            })
            
            # Claude will use tool results to continue in the next loop
        
        if iteration == max_iterations - 1:
            logger.warning("Agent loop reached max iterations")
    
    async def explain_research_term_streaming(self, text: str) -> AsyncGenerator[str, None]:
        """Use MCP server to explain research terms and generate streaming response with Claude"""
        logger.info("Starting research term explanation for: %s", text[:50])
        
        try:
            # Check if MCP session is initialized
            if not self.session:
                yield f"data: {json.dumps({'type': 'error', 'content': 'MCP server not initialized'})}\n\n"
                return
            
            # Get available tools from MCP server
            logger.info("Fetching available tools from MCP server")
            tools_result = await self.session.list_tools()
            logger.info("Available tools: %s", [tool.name for tool in tools_result.tools])
            
            # Convert MCP tools to Claude API tool format
            claude_tools = []
            for tool in tools_result.tools:
                claude_tools.append({
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema
                })
            
            # Initial message
            messages = [
                {
                    "role": "user",
                    "content": f"""You are a research term explainer. Your task is to explain the term: '{text}'

Follow these steps in order:

Step 1: Search for relevant papers
- If you know landmark/seminal papers for this term, search by exact title
- Search using the original term '{text}' as a keyword
- Search using related technical terms, variations, or more specific keywords
- Use multiple search queries to gather approximately 20-30 papers total
- Use max_results parameter appropriately for each search

Step 2: Filter papers based on abstracts
- Read the abstract of each retrieved paper carefully
- Select only papers that are directly relevant to explaining '{text}'
- Exclude papers that only mention the term tangentially
- Aim to select the top 10 most relevant papers (or fewer if less than 10 are truly relevant)
- Prioritize: foundational papers, seminal works, survey papers, and highly-cited research

Step 3: Write the explanation
- Based on the abstracts and content of the selected papers, write a comprehensive explanation of '{text}'
- Include: definition, key concepts, applications, and significance in the field
- Reference specific papers when explaining concepts (e.g., "as introduced in [Paper Title]")
- Use proper Markdown format with double line breaks between sections

Step 4: Display the selected papers
- At the end, show the 10 most relevant papers
- IMPORTANT: Use the ACTUAL pdf_url from each paper result
- Format each paper link like this example:
  - [Attention is All You Need](https://arxiv.org/pdf/1706.03762) - Introduces the Transformer architecture
- Replace the title and URL with the actual values from the search results
- Do NOT use placeholder text like "(arXiv URL)" - use the real PDF URL returned in the search results

## Related Papers

[List the actual papers here with their real PDF URLs]

Format requirements:
- Use proper Markdown with clear line breaks
- Use double line breaks between sections
- Important: In the explanation text (Step 3), you must insert a newline character (\n) after every sentence (ending in '.').
- Make the explanation evidence-based using the paper abstracts
- **Always use the actual PDF URLs from the search results, never placeholder text**

Important: Your explanation should be grounded in the actual content of the papers you found, not just general knowledge.
"""
}
            ]
            
            logger.info("Starting MCP-enabled agent loop")
            
            # Run agent loop (acting like an MCP client)
            async for event in self._run_agent_loop(messages, claude_tools):
                yield f"data: {json.dumps(event)}\n\n"
            
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            logger.info("Research term explanation completed")
        
        except Exception as e:
            logger.error("Error in explain_research_term_streaming: %s", str(e), exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': f'Error processing request: {str(e)}'})}\n\n"
            
mcp_client = MCPClient()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await mcp_client.start_mcp_server()
    yield
    # Shutdown
    await mcp_client.stop_mcp_server()

app = FastAPI(title="arXiv Research Term Explainer API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000"],  # Allow only necessary origins
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "status": "ok",
        "message": "arXiv Research Term Explainer API is running.",
        "anthropic_configured": bool(os.getenv("ANTHROPIC_API_KEY"))
    }
    
@app.post("/explain-research-term")
async def explain_research_term(request: TextRequest):
    logger.info("Received explain research term request")
    logger.info("Term length: %d", len(request.text))
    logger.info("Term: %s", request.text[:100] + "..." if len(request.text) > 100 else request.text)
    
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.error("Anthropic API key is not configured")
        raise HTTPException(
            status_code=500,
            detail="Anthropic API key is not configured."
        )
    
    logger.info("Starting streaming response")
    return StreamingResponse(
        mcp_client.explain_research_term_streaming(request.text),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )