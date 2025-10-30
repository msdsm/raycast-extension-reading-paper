import asyncio
from mcp.server import Server
from mcp.types import Tool, TextContent
import mcp.server.stdio
import arxiv
mcp_server = Server("text-length-server")

@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_papers",
            description="Search arXiv papers by keyword, title, author, abstract, or categories. Returns a list of papers with basic information.",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "General keyword to search across all fields"
                    },
                    "title": {
                        "type": "string",
                        "description": "Keyword to search in paper titles"
                    },
                    "author": {
                        "type": "string",
                        "description": "Author name to search for"
                    },
                    "abstract": {
                        "type": "string",
                        "description": "Keyword to search in paper abstracts"
                    },
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "arXiv categories to filter by. Examples: cs.AI (Artificial Intelligence), cs.LG (Machine Learning), cs.CL (Computational Linguistics), cs.CV (Computer Vision), stat.ML (Statistics - Machine Learning)"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of papers to return",
                        "default": 10
                    }
                },
            }
        ),
        Tool(
            name="search_with_multiple_keywords",
            description="Search for papers that contain ALL of the specified keywords. Useful for finding papers on specific topics.",
            inputSchema={
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of keywords that must all be present in the paper"
                    },
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "arXiv categories to filter by (optional)"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of papers to return",
                        "default": 10
                    }
                },
                "required": ["keywords"]
            }
        ),
    ]
    
@mcp_server.call_tool()
async def call_tool(tool_name: str, arguments: dict) -> list[TextContent]:
    if tool_name == "search_papers":
        keyword = arguments.get("keyword")
        title = arguments.get("title")
        author = arguments.get("author")
        abstract = arguments.get("abstract")
        categories = arguments.get("categories")
        max_results = arguments.get("max_results", 10)
        
        # Build query
        query_parts = []
        
        if title:
            query_parts.append(f'ti:"{title}"')
        if author:
            query_parts.append(f'au:"{author}"')
        if abstract:
            query_parts.append(f'abs:"{abstract}"')
        if categories:
            cat_query = " OR ".join([f'cat:{cat}' for cat in categories])
            query_parts.append(f'({cat_query})')
        if keyword:
            query_parts.append(f'all:"{keyword}"')
        
        query = " AND ".join(query_parts) if query_parts else keyword or ""
        
        if not query:
            return [TextContent(
                type="text",
                text="Error: At least one search parameter is required."
            )]
        
        # Execute search
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance,
            sort_order=arxiv.SortOrder.Descending
        )
        client = arxiv.Client()
        papers = []
        
        for result in client.results(search):
            paper_info = {
                'title': result.title,
                'authors': [author.name for author in result.authors],
                'summary': result.summary[:300] + "..." if len(result.summary) > 300 else result.summary,
                'published': result.published.strftime("%Y-%m-%d"),
                'pdf_url': result.pdf_url,
                'entry_id': result.entry_id,
                'categories': result.categories,
                'primary_category': result.primary_category
            }
            papers.append(paper_info)
        
        # Format results
        if not papers:
            result_text = f"No papers found for query: {query}"
        else:
            result_text = f"Found {len(papers)} papers:\n\n"
            for i, paper in enumerate(papers, 1):
                result_text += f"{i}. {paper['title']}\n"
                result_text += f"   Authors: {', '.join(paper['authors'][:3])}"
                if len(paper['authors']) > 3:
                    result_text += f" et al. ({len(paper['authors'])} total)"
                result_text += f"\n   Published: {paper['published']}\n"
                result_text += f"   Categories: {', '.join(paper['categories'])}\n"
                result_text += f"   PDF: {paper['pdf_url']}\n"
                result_text += f"   Summary: {paper['summary']}\n\n"
        
        return [TextContent(type="text", text=result_text)]
    elif tool_name == "search_with_multiple_keywords":
        keywords = arguments.get("keywords", [])
        categories = arguments.get("categories")
        max_results = arguments.get("max_results", 10)
        
        if not keywords:
            return [TextContent(
                type="text",
                text="Error: At least one keyword is required."
            )]
        
        # Build query
        query_parts = [f'all:"{kw}"' for kw in keywords]
        
        if categories:
            cat_query = " OR ".join([f'cat:{cat}' for cat in categories])
            query_parts.append(f'({cat_query})')
        
        query = " AND ".join(query_parts)
        
        # Execute search
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance,
            sort_order=arxiv.SortOrder.Descending
        )
        
        client = arxiv.Client()
        papers = []
        for result in client.results(search):
            paper_info = {
                'title': result.title,
                'authors': [author.name for author in result.authors],
                'summary': result.summary[:300] + "..." if len(result.summary) > 300 else result.summary,
                'published': result.published.strftime("%Y-%m-%d"),
                'pdf_url': result.pdf_url,
                'entry_id': result.entry_id,
                'categories': result.categories
            }
            papers.append(paper_info)
        
        # Format results
        if not papers:
            result_text = f"No papers found containing all keywords: {', '.join(keywords)}"
        else:
            result_text = f"Found {len(papers)} papers containing all keywords ({', '.join(keywords)}):\n\n"
            for i, paper in enumerate(papers, 1):
                result_text += f"{i}. {paper['title']}\n"
                result_text += f"   Authors: {', '.join(paper['authors'][:3])}"
                if len(paper['authors']) > 3:
                    result_text += f" et al."
                result_text += f"\n   Published: {paper['published']}\n"
                result_text += f"   PDF: {paper['pdf_url']}\n"
                result_text += f"   Summary: {paper['summary']}\n\n"
        
        return [TextContent(type="text", text=result_text)]
    else:
        raise ValueError(f"Unknown tool: {tool_name}")

async def run_mcp_server():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await mcp_server.run(
            read_stream,
            write_stream,
            mcp_server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(run_mcp_server())