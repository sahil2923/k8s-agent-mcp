from dotenv import load_dotenv
load_dotenv()
import os
import openai
import json
import httpx
import asyncio

# Step 1: Set up environment variables
openai.api_key = os.getenv("OPENAI_API_KEY")
MCP_SERVER_URL = "http://localhost:8080/mcp/execute"
SESSION_ID = "vscode-session"

# Step 2: Prompt template to convert natural language to MCP command
PROMPT_TEMPLATE = """
You're a command parser for Kubernetes.

Given a user message, convert it to a JSON object with:
- `instruction`: one of ["k8s_resource_status", "describe_pod", "get_pod_logs", "get_pod"]
- `params`: dictionary of parameters like `resource_type`, `namespace`, `pod_name`, `container`

Return **only the JSON**.

User message: "{message}"
"""

# Step 3: Ask ChatGPT to parse natural language
async def parse_nl_to_command(message: str) -> dict:
    prompt = PROMPT_TEMPLATE.format(message=message)
    response = await openai.ChatCompletion.acreate(
        model="gpt-4o",  # or gpt-4-turbo / gpt-3.5-turbo
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=150,
    )
    raw_output = response.choices[0].message.content.strip()

    # Remove markdown code block backticks if present
    if raw_output.startswith("```") and raw_output.endswith("```"):
        lines = raw_output.splitlines()
        lines = [line for line in lines if not line.strip().startswith("```")]
        raw_output = "\n".join(lines).strip()

    try:
        return json.loads(raw_output)
    except json.JSONDecodeError:
        print("⚠️ Failed to parse response from ChatGPT:")
        print(raw_output)
        return None

# Step 4: Send parsed command to MCP Server
async def call_mcp_server(command_json: dict):
    async with httpx.AsyncClient() as client:
        response = await client.post(MCP_SERVER_URL, json=command_json, params={"session_id": SESSION_ID})
        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ MCP Server Error: {response.text}")
            return None

# Step 5: Run in terminal
async def main():
    user_input = input("🧠 Enter your K8s command (natural language): ")

    # 1. Parse into instruction
    command_json = await parse_nl_to_command(user_input)
    if not command_json:
        print("❌ Failed to parse natural language.")
        return

    print(f"\n✅ Parsed command:\n{json.dumps(command_json, indent=2)}")

    # 2. Send to MCP
    result = await call_mcp_server(command_json)
    if result:
        print("\n📦 MCP Output:")
        print(f"Command: {result['command']}")
        print(f"Output:\n{result['output']}")

# Entry point
if __name__ == "__main__":
    asyncio.run(main())
