"""
BGPT Paper Search Skill

Search scientific papers and retrieve structured experimental data extracted 
from full-text studies via the BGPT MCP server.
"""

NAME = "bgpt_paper_search"
DESCRIPTION = "Search scientific papers and retrieve structured experimental data extracted from full-text studies via the BGPT MCP server. Returns 25+ fields per paper including methods, results, sample sizes, quality scores, and conclusions."
TRIGGERS = [
    "search papers", "find papers", "bgpt", "literature review", 
    "scientific papers", "paper search", "experimental data", 
    "systematic review", "meta-analysis", "evidence synthesis"
]

def run(query, limit=10, fields=None):
    """Search for scientific papers using BGPT MCP server.
    
    Args:
        query: Natural language search query (e.g., "transformer architecture attention mechanism")
        limit: Maximum number of results to return (default: 10)
        fields: Optional list of specific fields to return
    
    Returns:
        Structured results from BGPT including title, authors, methods, 
        results, sample sizes, quality scores, and conclusions.
    
    Note: Requires BGPT MCP server to be configured in the agent's MCP settings.
    See setup instructions in the skill documentation.
    """
    return {
        "status": "info",
        "message": "BGPT Paper Search requires MCP server configuration.",
        "setup_required": True,
        "mcp_config": {
            "command": "npx",
            "args": ["mcp-remote", "https://bgpt.pro/mcp/sse"]
        },
        "usage": "Once MCP is configured, use the search_papers tool via the agent's MCP interface:\n  Search for papers about: \"your query here\"",
        "example_queries": [
            "transformer architecture attention mechanism",
            "neural network training optimization techniques",
            "vector database similarity search performance",
            "LLM fine-tuning methods comparison",
            "retrieval augmented generation RAG evaluation"
        ],
        "pricing": {
            "free_tier": "50 searches per network, no API key required",
            "paid": "$0.01 per result with API key from https://bgpt.pro/mcp"
        }
    }

if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1:
        query = sys.argv[1]
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        result = run(query, limit)
        print(json.dumps(result, indent=2))