import os
import json
import logging
import time
import utils
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from llama_stack_client import LlamaStackClient
from llama_stack_client.lib.agents.agent import Agent

# Load environment variables
load_dotenv()

# Server configurations
def get_server_configs():
    """Return test configurations for different MCP servers."""
    return {
        "ansible": {
            "file_path": './queries/anisble_queries.json',
            "mcp_url": os.getenv('ANSIBLE_MCP_SERVER_URL'),
            "toolgroup_id": "mcp::ansible"
        },
        "github": {
            "file_path": './queries/github_queries.json',
            "mcp_url": os.getenv('GITHUB_MCP_SERVER_URL'),
            "toolgroup_id": "mcp::github"
        },
        "openshift": {
            "file_path": './queries/ocp_queries.json',
            "mcp_url": os.getenv('OCP_MCP_SERVER_URL'),
            "toolgroup_id": "mcp::openshift"
        },
        "custom": {
            "file_path": './queries/custom_queries.json',
            "mcp_url": os.getenv('CUSTOM_MCP_SERVER_URL'),
            "toolgroup_id": "mcp::custom_tool"
        }
    }


def load_queries(file_path: str) -> List[Dict[str, str]]:
    """Load query strings from a JSON file."""
    try:
        with open(file_path, 'r') as file:
            data = json.load(file)

        if not isinstance(data, dict) or 'queries' not in data:
            raise ValueError(f"Invalid JSON format in {file_path}")

        # Return full query objects with ID for better test identification
        return data['queries']
    except FileNotFoundError:
        print(f"Query file not found: {file_path}")
        return []
    except json.JSONDecodeError:
        print(f"Invalid JSON in file: {file_path}")
        return []


def get_query_id(query_obj):
    """Extract an ID from a query object for better test identification."""
    if isinstance(query_obj, dict) and 'id' in query_obj:
        return query_obj['id']
    elif isinstance(query_obj, dict) and 'query' in query_obj:
        # Use first few words of query if no ID is available
        words = query_obj['query'].split()[:5]
        return '_'.join(words).lower().replace(',', '').replace('.', '')
    return "unknown_query"


def register_toolgroup_if_needed(
    client: LlamaStackClient,
    toolgroup_id: str,
    mcp_url: str,
    logger: logging.Logger
) -> bool:
    """Register a toolgroup if it doesn't exist. Returns success status."""
    try:
        registered_tools = client.tools.list()
        registered_toolgroups = set(t.toolgroup_id for t in registered_tools)

        logger.info(f"Available toolgroups: {registered_toolgroups}")

        if toolgroup_id not in registered_toolgroups:
            logger.info(f"Registering toolgroup: {toolgroup_id}")
            client.toolgroups.register(
                toolgroup_id=toolgroup_id,
                provider_id="model-context-protocol",
                mcp_endpoint={"uri": mcp_url},
            )
            logger.info(f"Successfully registered toolgroup: {toolgroup_id}")
        else:
            logger.info(f"Toolgroup {toolgroup_id} is already registered")

        return True
    except Exception as e:
        logger.error(f"Failed to register toolgroup {toolgroup_id}: {e}")
        return False


def execute_query(
    client: LlamaStackClient,
    prompt: str,
    model: str,
    toolgroup_id: str,
    instructions: Optional[str] = None,
    max_tokens: int = 4096
) -> Dict[str, Any]:
    """Execute a single query."""
    if instructions is None:
        instructions = """You are a helpful assistant. You have access to a number of tools.
            Whenever a tool is called, be sure return the Response in a friendly and helpful tone.
            When you are asked to search the web you must use a tool. Keep answers concise.
            """

    # Create agent with tools
    agent = Agent(
        client,
        model=model,
        instructions=instructions,
        tools=[toolgroup_id],
        tool_config={"tool_choice": "auto"},
        sampling_params={"max_tokens": max_tokens}
    )

    # Create session
    session_id = agent.create_session(session_name=f"Test_{toolgroup_id}_{int(time.time())}")

    # Execute query
    turn_response = agent.create_turn(
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        session_id=session_id,
        stream=False
    )

    return turn_response


def run_test(server_type, model, query_obj, llama_client, logger):
    """Run a single test for a specific server type, model, and query."""
    server_configs = get_server_configs()
    config = server_configs[server_type]
    query_id = get_query_id(query_obj)
    prompt = query_obj['query']
    expected_tool_call = query_obj['tool_call']
    tool_call_match = False
    inference_not_empty = False

    # Register MCP URL if in config
    if config["mcp_url"]:
        logger.info(f"Registering {server_type}")
        # Set up for the query (register toolgroup)
        # If the server is not already registered or can't be registered skip
        if not register_toolgroup_if_needed(
            llama_client,
            config["toolgroup_id"],
            config["mcp_url"],
            logger
        ):
            return False

    logger.info(f"Testing query '{query_id}' for {server_type} with model {model}")
    logger.info(f"Query: {prompt[:50]}...")

    try:
        # Execute query
        response = execute_query(
            llama_client,
            prompt,
            model,
            config["toolgroup_id"]
        )
        # Get Tool execution and Inference steps
        steps = response.steps

        #Get tool used
        try:
            tools_used = steps[1].tool_calls[0].tool_name
        except Exception as e:
            logger.error(f"Error extracting tool name: {e}")
            tools_used = None
        tool_call_match = True if tools_used == expected_tool_call else False
        logger.info(f"Tool used: {tools_used} Tool expected: {expected_tool_call} match: {tool_call_match} ")

        #Check inference was not empty
        final_response = ""
        try:
            final_response = steps[2].api_model_response.content.strip()
            inference_not_empty = True if final_response != '' else False
        except Exception as e:
            logger.error(f"Error checking inference content: {e}")
            inference_not_empty = False
        logger.info(f'Inference not empty: {inference_not_empty}')
        logger.info(f"Query '{query_id}' succeeded with model {model} and the response \n {final_response}")

        # Record success metrics
        utils.add_metric(
            server_type=server_type,
            model=model,
            query_id=query_id,
            status="SUCCESS",
            tool_call_match=tool_call_match,
            inference_not_empty=inference_not_empty,
        )

        return True

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Query '{query_id}' failed with model {model}: {error_msg}")

        # Record failure metrics
        utils.add_metric(
            server_type=server_type,
            model=model,
            query_id=query_id,
            status="FAILURE",
            tool_call_match=False,
            inference_not_empty=False,
            error=error_msg
        )

        return False


def main():
    """Main function to run all tests."""
    # Set up logger
    logger =utils.setup_logger()

    # Create client
    base_url = os.getenv('REMOTE_BASE_URL')
    if not base_url:
        logger.error("REMOTE_BASE_URL environment variable not set")
        return

    llama_client = LlamaStackClient(base_url=base_url)

    # Define models to test
    # make sure they are available in your LLS server
    models = ["meta-llama/Llama-3.2-3B-Instruct",
              "ibm-granite/granite-3.2-8b-instruct",]
            #   "watt-ai/watt-tool-8B",
            #   "meta-llama/Llama-3.3-70B-Instruct"]

    # Get server configurations
    server_configs = get_server_configs()

    # Track statistics
    total_tests = 0
    successful_tests = 0

    # Loop through models (outermost loop)
    for model in models:
        logger.info(f"\n=== Testing with model: {model} ===\n")

        # Loop through server types
        for server_type, config in server_configs.items():

            # Load queries for this server
            queries = load_queries(config["file_path"])
            if not queries:
                logger.info(f"No queries found for {server_type}")
                continue

            logger.info(f"Running {len(queries)} queries for {server_type}")

            # Loop through queries (innermost loop)
            for query_obj in queries:
                total_tests += 1
                success = run_test(server_type, model, query_obj, llama_client, logger)
                if success:
                    successful_tests += 1

    # Print summary
    logger.info(f"\n=== Test Summary ===")
    logger.info(f"Total tests: {total_tests}")
    logger.info(f"Successful tests: {successful_tests}")
    logger.info(f"Failed tests: {total_tests - successful_tests}")
    if total_tests > 0:
        success_rate = (successful_tests / total_tests) * 100
        logger.info(f"Success rate: {success_rate:.1f}%")

    # Generate plots
    logger.info(f"\n=== Generating plots ===")
    utils.get_analysis_plots()


if __name__ == "__main__":
    main()
