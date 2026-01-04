# Joblock - Invisible AI Overlay Assistant
# Copyright (C) 2026 Diogo Pasi de Oliveira
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from typing import TypedDict, Annotated, List
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
)
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver
from langchain_openai import ChatOpenAI


class ChatState(TypedDict):
    messages: Annotated[List[BaseMessage], "chat_history"]
    mode: str  # "ask" | "append"


def build_chat_graph(model_name: str):
    llm = ChatOpenAI(model=model_name, temperature=0.2)

    def router(state: ChatState):
        return state["mode"]

    def call_llm(state: ChatState) -> ChatState:
        resp = llm.invoke(state["messages"])
        return {
            "messages": state["messages"] + [resp],
            "mode": "ask",
        }

    def append_only(state: ChatState) -> ChatState:
        return state

    graph = StateGraph(ChatState)
    graph.add_node("call_llm", call_llm)
    graph.add_node("append_only", append_only)

    graph.set_entry_point("router")
    graph.add_conditional_edges(
        "router",
        router,
        {
            "ask": "call_llm",
            "append": "append_only",
        },
    )

    graph.add_edge("call_llm", END)
    graph.add_edge("append_only", END)

    saver = InMemorySaver()
    app = graph.compile(checkpointer=saver)
    return app
