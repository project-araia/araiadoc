import shlex
import subprocess
import sys
from pathlib import Path

from fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("climpdf-server")

# Define project root and data directory
# Assuming this file is located at src/climpdfgetter/mcp_server.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"


@mcp.resource("data://{path}")
def read_data_file(path: str) -> str:
    """
    Read a text file from the data directory.

    Args:
        path: The relative path to the file within the 'data' directory.
    """
    # Construct absolute path and resolve symlinks
    try:
        file_path = (DATA_DIR / path).resolve()

        # Security check: Ensure the file is within the DATA_DIR
        # This prevents directory traversal attacks (e.g., ../../etc/passwd)
        if not str(file_path).startswith(str(DATA_DIR.resolve())):
            raise ValueError("Access denied: Path is outside the allowed data directory.")

        if not file_path.exists():
            return f"Error: File not found at {path}"

        if not file_path.is_file():
            return f"Error: {path} is not a file."

        # Attempt to read as text
        return file_path.read_text(encoding="utf-8", errors="replace")

    except Exception as e:
        return f"Error reading file {path}: {str(e)}"


@mcp.tool()
def climpdf(args: str) -> str:
    """
    Run the 'climpdf' command-line tool with the specified arguments.

    Args:
        args: A string of arguments to pass to the climpdf command (e.g., 'crawl-epa 0 10 -t "Heat Waves"')
    """
    try:
        # Split arguments string into a list, handling quotes correctly
        cmd_args = shlex.split(args)
    except ValueError as e:
        return f"Error parsing argument string: {str(e)}"

    # Construct the command to run via the python interpreter to match the environment
    # We invoke the module directly to ensure we use the current source/env
    cmd = [sys.executable, "-m", "climpdfgetter.crawl"] + cmd_args

    try:
        # Run the command
        # We capture stdout/stderr to return to the LLM
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, check=False  # We handle return codes manually
        )

        output = []
        if result.stdout:
            output.append("STDOUT:")
            output.append(result.stdout)
        if result.stderr:
            output.append("STDERR:")
            output.append(result.stderr)

        if result.returncode != 0:
            output.append(f"\nCommand failed with exit code {result.returncode}")

        return "\n".join(output) if output else "Command executed with no output."

    except Exception as e:
        return f"failed to execute command: {str(e)}"


@mcp.tool()
def analyze_with_llm(path: str, prompt: str) -> str:
    """
    Read a file from the data directory and process it with an LLM (OpenAI).
    Requires OPENAI_API_KEY environment variable to be set.

    Args:
        path: Path to the file in the data directory.
        prompt: The instruction for the LLM (e.g., "Summarize this text").
    """
    import os

    from openai import OpenAI

    # Reuse the logic from read_data_file to safely get content
    try:
        # Construct absolute path and resolve symlinks
        file_path = (DATA_DIR / path).resolve()

        # Security check
        if not str(file_path).startswith(str(DATA_DIR.resolve())):
            return "Error: Access denied. Path is outside the allowed data directory."

        if not file_path.exists():
            return f"Error: File not found at {path}"

        content = file_path.read_text(encoding="utf-8", errors="replace")

        # Limit content length to avoid exceeding token limits (crude check)
        # Adjust as needed (e.g., 100k chars ~ 25k tokens)
        if len(content) > 100000:
            content = content[:100000] + "\n...[TRUNCATED]..."

    except Exception as e:
        return f"Error reading file for analysis: {str(e)}"

    try:
        api_key = os.environ.get("OPENAI_API_KEY")
        base_url = os.environ.get("OPENAI_BASE_URL")
        model = os.environ.get("LLM_MODEL", "gpt-4o")

        if not api_key:
            return "Error: OPENAI_API_KEY environment variable not set."

        client = OpenAI(api_key=api_key, base_url=base_url)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant analyzing scientific documents."},
                {"role": "user", "content": f"{prompt}\n\nDocument Content:\n{content}"},  # noqa
            ],
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"Error calling OpenAI API: {str(e)}"


@mcp.tool()
def count_local(source: str) -> str:
    """
    Count the number of downloaded files from a given source (e.g., 'OSTI', 'EPA').

    Args:
        source: The source name to count files for.
    """
    from climpdfgetter.utils import _count_local

    try:
        count = _count_local(source)
        return f"Found {count} files for source '{source}'."
    except Exception as e:
        return f"Error counting local files: {str(e)}"


# --- Prompts ---


@mcp.prompt()
def crawl_epa_guide() -> str:
    """Returns a guide and template for using the 'crawl-epa' command."""
    return """You can use the `climpdf` tool to crawl EPA documents.

The command format is: `climpdf crawl-epa <start_idx> <stop_idx> -t "<search_term>"`

- `start_idx`: The starting index for the search results (e.g., 0).
- `stop_idx`: The ending index for the search results (e.g., 100).
- `-t`: The search term (can be used multiple times).

Example: Crawl first 50 documents for "Heat Waves"
`climpdf crawl-epa 0 50 -t "Heat Waves"`
"""


@mcp.prompt()
def crawl_osti_guide() -> str:
    """Returns a guide and template for using the 'crawl-osti' command."""
    return """You can use the `climpdf` tool to crawl OSTI documents.

The command format is: `climpdf crawl-osti <start_year> [stop_year] -t "<search_term>"`

- `start_year`: The year to start crawling from.
- `stop_year`: (Optional?) The year to stop crawling.
- `-t`: The search term.

Example: Crawl documents from 2020 related to "Floods"
`climpdf crawl-osti 2020 -t "Floods"`
"""


@mcp.prompt()
def convert_guide() -> str:
    """Returns a guide for using the 'convert' command."""
    return """You can use the `climpdf` tool to convert PDFs or process data.

Common conversion commands:
- `climpdf convert`: Run the general conversion process.
- `climpdf epa-ocr-to-json`: Convert EPA OCR text files to JSON format.

Make sure to check the help for specific arguments if needed: `climpdf convert --help`
"""


@mcp.prompt()
def count_stats_guide() -> str:
    """Returns a guide for counting local or remote files."""
    return """You can use `climpdf` to get statistics on data.

- `climpdf count-local`: Count locally downloaded files.
- `climpdf count-remote-osti <start_year> <stop_year> -t "<term>"`: Count potential results on OSTI.

Example: Count local files
`climpdf count-local`
"""


@mcp.prompt()
def complete_semantic_scholar_guide() -> str:
    """Returns a guide for using the 'complete-semantic-scholar' command."""
    return """You can use the `climpdf` tool to augment data with Semantic Scholar.

The command format is:
`climpdf complete-semantic-scholar <input_file> -i <input_format> [-m <metadata_file>] [-o <output_format>]`

Arguments:
- `input_file`: Path to the input file or directory.
- `-i` / `--input_format`: Format of input (`csv`, `checkpoint`, `pes2o`, `combined`).
- `-m` / `--input_metadata_file`: (Optional) Metadata CSV file, required for `combined` mode.
- `-o` / `--output_format`: Format of output (`metadata`, `pdf`, `combined`).

Example:
`climpdf complete-semantic-scholar data/input.csv -i csv -o metadata`
"""


if __name__ == "__main__":
    mcp.run()
