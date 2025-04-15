# Code bellow written following examples here: https://llama-stack.readthedocs.io/en/latest/building_applications
from llama_stack_client.lib.agents.agent import Agent
from llama_stack_client.lib.agents.event_logger import EventLogger
from llama_stack_client import LlamaStackClient
import logging
import os
from dotenv import load_dotenv
import json

def test_mcp_server(file_path, REMOTE_MCP_URL, model, mcp_server_name):

    # Open the JSON file and load its content
    with open(file_path, 'r') as file:
        data = json.load(file)

    queries = data['queries']
    user_prompts = [query['query'] for query in queries]

    logger = logging.getLogger(__name__)
    if not logger.hasHandlers():
        logger.setLevel(logging.INFO)
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(message)s')
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    logger.info(f"Testing {mcp_server_name} toolgroup ")
    logger.info(f'Model is {model} \n \n')


    # Connect to a llama stack server
    base_url = os.getenv('REMOTE_BASE_URL')
    client = LlamaStackClient(base_url=base_url)
    logger.info(f"Connected to Llama Stack server @ {base_url} \n")

    # Get tool info and register tools
    registered_tools = client.tools.list()
    registered_tools_identifiers = [t.identifier for t in registered_tools]
    registered_toolgroups = [t.toolgroup_id for t in registered_tools]

    if mcp_server_name not in registered_toolgroups:
        # Register MCP tools
        client.toolgroups.register(
            toolgroup_id=mcp_server_name,
            provider_id="model-context-protocol",
            mcp_endpoint={"uri":REMOTE_MCP_URL},
            )

    logger.info(f"""Your Server has access the the following toolgroups:
    {set(registered_toolgroups)}
    """)

    for prompt in user_prompts:
        # Create simple agent with tools
        agent = Agent(
            client,
            model=model,
            instructions = """You are a helpful assistant. You have access to a number of tools.
            Whenever a tool is called, be sure return the Response in a friendly and helpful tone.
            When you are asked to search the web you must use a tool. keep answer concise
            """ ,
            tools=[mcp_server_name],
            tool_config={"tool_choice":"auto"},
            sampling_params={"max_tokens":4096}
        )
        session_id = agent.create_session(session_name="Conversation_demo")
        turn_response = agent.create_turn(
            messages=[
                {
                    "role":"user",
                    "content": prompt
                }
            ],
            session_id=session_id
        )
        for log in EventLogger().log(turn_response):
            log.print()


if __name__ == "__main__":
    load_dotenv()

    ansible_mcp_server_url = os.getenv('ANSIBLE_MCP_SERVER_URL')
    github_mcp_server_url = os.getenv('GITHUB_MCP_SERVER_URL')
    ocp_mcp_server_url = os.getenv('OCP_MCP_SERVER_URL')
    custom_mcp_server_url = os.getenv('CUSTOM_MCP_SERVER_URL')
    # Call the function with the file path
    ansible_file_path = './queries/ansible_queries.json'
    custom_file_path = './queries/custom_queries.json'
    github_file_path = './queries/github_queries.json'
    openshift_file_path = './queries/ocp_queries.json'

    test_mcp_server(ansible_file_path,ansible_mcp_server_url,"meta-llama/Llama-3.2-3B-Instruct","mcp::ansible")
    test_mcp_server(github_file_path,github_mcp_server_url,"ibm-granite/granite-3.2-8b-instruct","mcp::github")
    test_mcp_server(openshift_file_path,ocp_mcp_server_url,"ibm-granite/granite-3.2-8b-instruct","mcp::openshift")
    test_mcp_server(custom_file_path,custom_mcp_server_url,"meta-llama/Llama-3.2-3B-Instruct","mcp::custom_tool")
