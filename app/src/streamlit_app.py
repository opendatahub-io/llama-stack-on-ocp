import streamlit as st
from llama_stack_client import LlamaStackClient, Agent, APIConnectionError
from llama_stack_client.lib.agents.react.agent import ReActAgent
from llama_stack_client.lib.agents.react.tool_parser import ReActOutput
from dotenv import load_dotenv
import os
import uuid
import json

load_dotenv()

BASE_URL = os.getenv("REMOTE_BASE_URL")
TOOL_DEBUG = False

client = LlamaStackClient(base_url=BASE_URL)

try:
    models = client.models.list()
    connected = True
except APIConnectionError:
    models = []
    connected = False
model_list = [model.identifier for model in 
              models if model.api_model_type == "llm"]

tool_groups = client.toolgroups.list()
tool_groups_list = [tool_group.identifier for tool_group in 
                    tool_groups if tool_group.identifier.startswith("mcp::")]

def reset_agent():
    st.session_state.clear()
    st.cache_resource.clear()

st.title("Llama Stack + MCP Client")

with st.sidebar:
    if connected:
        st.markdown(":green[Connected]")
    else:
        st.markdown(":red[No Connection]")
    
    st.header("Model")
    model = st.selectbox(label="models", options=model_list,index=3, on_change=reset_agent)
    
    # Add agent type selector
    st.header("Agent Type")
    agent_type = st.radio(
        "Select Agent Type",
        ["Regular", "ReAct"],
        on_change=reset_agent
    )
    
    st.header("MCP Servers")
    toolgroup_selection = st.pills(label="Available Servers",options=tool_groups_list, selection_mode="multi",on_change=reset_agent)    
    
    grouped_tools = {}
    total_tools = 0
    for toolgroup_id in toolgroup_selection:
        tools = client.tools.list(toolgroup_id=toolgroup_id)
        grouped_tools[toolgroup_id] = [tool.identifier for tool in tools]
        total_tools += len(tools)

    st.markdown(f"Active Tools: 🛠 {total_tools}")

    for group_id, tools in grouped_tools.items():
        with st.expander(f"🔧 Tools from `{group_id}`"):
            for idx, tool in enumerate(tools, start=1):
                st.markdown(f"{idx}. `{group_id}:{tool}`")

    st.text_input(label="Install New Server", placeholder="MCP Server")

@st.cache_resource
def create_agent():
    if agent_type == "Regular":
        return Agent(client,
                  model=model,
                  instructions="You are a helpful assistant. When you use a tool always respond with a summary of the result.",
                  tools=toolgroup_selection,
                  sampling_params={"max_tokens":4096},
                )
    else:
        # Create ReAct agent
        return ReActAgent(
            client=client,
            model=model,
            tools=toolgroup_selection,
            instructions="You are a helpful assistant that uses reasoning to solve problems step by step. Break down complex problems into simpler steps.",
            response_format={
                "type": "json_schema",
                "json_schema": ReActOutput.model_json_schema(),
            },
            sampling_params={"max_tokens":4096},
        )

agent = create_agent()

if "agent_session_id" not in st.session_state: 
    st.session_state["agent_session_id"] = agent.create_session(session_name=f"mcp_demo_{uuid.uuid4()}")
session_id = st.session_state["agent_session_id"]

if "messages" not in st.session_state:
    st.session_state["messages"] = [{"role": "assistant", "content": "How can I help you?"}]

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input(placeholder=""):    
    
    with st.chat_message("user"):
        st.markdown(prompt)

    st.session_state.messages.append({"role": "user", "content": prompt})
    
    turn_response = agent.create_turn(
        session_id=session_id,
        messages=[{
            "role": "user",
            "content": prompt
        }],
        stream=True,
    )
    
    def response_generator(turn_response):
        for r in turn_response:
            if hasattr(r.event,"payload"):
                print(r.event.payload)
                if r.event.payload.event_type == "step_progress":
                    if hasattr(r.event.payload.delta, "text"):
                        yield r.event.payload.delta.text
                if r.event.payload.event_type == "step_complete":
                    if r.event.payload.step_details.step_type == "tool_execution":
                        if TOOL_DEBUG:
                            content_text = json.loads(r.event.payload.step_details.tool_responses[0].content)["text"] 
                            tool_name = r.event.payload.step_details.tool_calls[0].tool_name
                            tool_args = r.event.payload.step_details.tool_calls[0].arguments_json
                            tool_info = str({"tool_name":{tool_name}, "arguments":{tool_args}, "content":{content_text}})
                            yield f" 🛠 {tool_info} \n\n"
                        else:
                             yield f" 🛠 "            
            else:
                yield f"Error occurred in the Llama Stack Cluster: {r}"

    with st.chat_message("assistant"):
        response = st.write_stream(response_generator(turn_response))
    
    st.session_state.messages.append({"role": "assistant", "content": response})
