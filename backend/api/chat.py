"""
聊天 API 路由
支持 SSE 流式输出
"""
import json
import uuid
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent import MessagesState, create_agent
from langchain_core.messages import HumanMessage
from backend.api.callback import StreamingCallbackHandler

router = APIRouter()


class ChatRequest(BaseModel):
    """聊天请求模型"""
    query: str
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    model: str = "qwen-plus"


class ChatResponse(BaseModel):
    """聊天响应模型"""
    request_id: str
    session_id: str
    message: str
    finished: bool


async def stream_agent_response(query: str, session_id: str, request_id: str, model: str):
    """流式输出 Agent 响应"""
    import asyncio
    import queue
    from queue import Queue

    try:
        event_queue = Queue()
        accumulated_message = ""

        def on_token(token: str):
            print(f"[DEBUG] Received token: {repr(token[:50])}")
            event_queue.put({"kind": "token", "content": token})

        def on_event(event: dict):
            print(f"[DEBUG] Received tool event: {event}")
            event_queue.put({"kind": "event", "content": event})

        callback_handler = StreamingCallbackHandler(
            token_callback=on_token,
            event_callback=on_event,
        )
        react_graph = create_agent(callback_handler, model)
        state = MessagesState(messages=[HumanMessage(content=query)])
        config = {
            "configurable": {"thread_id": session_id},
            "recursion_limit": 50,
        }

        yield {
            "event": "message",
            "data": json.dumps(
                {
                    "type": "start",
                    "request_id": request_id,
                    "session_id": session_id,
                    "message": "已接收到你的任务，将立即开始处理...",
                    "finished": False,
                },
                ensure_ascii=False,
            ),
        }

        def run_agent():
            try:
                print(f"[DEBUG] Starting agent execution for query: {query[:50]}...")
                result = react_graph.invoke(state, config=config, debug=False)
                print(
                    "[DEBUG] Agent execution completed. "
                    f"Final message length: {len(callback_handler.final_message)}"
                )
                return result
            except Exception as e:
                print(f"[ERROR] Agent execution failed: {str(e)}")
                import traceback

                traceback.print_exc()
                event_queue.put({"kind": "error", "content": str(e)})
                return None

        loop = asyncio.get_event_loop()
        agent_future = loop.run_in_executor(None, run_agent)
        agent_done = False
        last_message_sent = ""

        while not agent_done:
            try:
                try:
                    item = event_queue.get_nowait()
                    if item.get("kind") == "error":
                        raise Exception(item["content"])

                    if item.get("kind") == "event":
                        event_payload = dict(item["content"])
                        event_payload.update(
                            {
                                "request_id": request_id,
                                "session_id": session_id,
                                "finished": False,
                            }
                        )
                        yield {
                            "event": "message",
                            "data": json.dumps(event_payload, ensure_ascii=False),
                        }
                        continue

                    token = item["content"]
                    accumulated_message += token
                    if accumulated_message != last_message_sent:
                        last_message_sent = accumulated_message
                        yield {
                            "event": "message",
                            "data": json.dumps(
                                {
                                    "type": "response",
                                    "request_id": request_id,
                                    "session_id": session_id,
                                    "message": accumulated_message,
                                    "finished": False,
                                },
                                ensure_ascii=False,
                            ),
                        }
                except queue.Empty:
                    if agent_future.done():
                        agent_done = True
                        result = await agent_future

                        while not event_queue.empty():
                            try:
                                item = event_queue.get_nowait()
                                if item.get("kind") == "error":
                                    raise Exception(item["content"])
                                if item.get("kind") == "event":
                                    event_payload = dict(item["content"])
                                    event_payload.update(
                                        {
                                            "request_id": request_id,
                                            "session_id": session_id,
                                            "finished": False,
                                        }
                                    )
                                    yield {
                                        "event": "message",
                                        "data": json.dumps(event_payload, ensure_ascii=False),
                                    }
                                    continue
                                accumulated_message += item["content"]
                            except queue.Empty:
                                break

                        final_message = callback_handler.final_message or accumulated_message

                        if not final_message and result:
                            if isinstance(result, dict) and "messages" in result:
                                from langchain_core.messages import AIMessage, ToolMessage

                                chart_config = None
                                for msg in result["messages"]:
                                    if isinstance(msg, ToolMessage):
                                        if isinstance(msg.content, dict) and "chart_config" in msg.content:
                                            chart_config = msg.content["chart_config"]

                                for msg in reversed(result["messages"]):
                                    if isinstance(msg, AIMessage) and hasattr(msg, "content"):
                                        final_message = msg.content
                                        if chart_config:
                                            chart_json = json.dumps(chart_config, ensure_ascii=False, indent=2)
                                            final_message = f"{final_message}\n\n```json\n{chart_json}\n```"
                                        break

                        if not final_message:
                            final_message = "处理完成，但未收到响应内容。"

                        yield {
                            "event": "message",
                            "data": json.dumps(
                                {
                                    "type": "response",
                                    "request_id": request_id,
                                    "session_id": session_id,
                                    "message": final_message,
                                    "tool_events": callback_handler.tool_events,
                                    "finished": True,
                                },
                                ensure_ascii=False,
                            ),
                        }
                    else:
                        await asyncio.sleep(0.1)
            except Exception as e:
                agent_done = True
                raise e

    except Exception as e:
        yield {
            "event": "error",
            "data": json.dumps(
                {
                    "type": "error",
                    "request_id": request_id,
                    "session_id": session_id,
                    "message": f"处理请求时出错: {str(e)}",
                    "finished": True,
                },
                ensure_ascii=False,
            ),
        }


@router.post("/query")
async def chat_query(request: ChatRequest):
    """聊天查询接口（SSE 流式输出）"""
    session_id = request.session_id or "default"
    request_id = request.request_id or str(uuid.uuid4())

    try:
        from sse_starlette.sse import EventSourceResponse

        return EventSourceResponse(
            stream_agent_response(
                query=request.query,
                session_id=session_id,
                request_id=request_id,
                model=request.model,
            )
        )
    except ImportError:
        async def generate():
            async for event in stream_agent_response(
                query=request.query,
                session_id=session_id,
                request_id=request_id,
                model=request.model,
            ):
                yield f"event: {event['event']}\ndata: {event['data']}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "ChatBI API"}


@router.get("/models")
async def get_all_models():
    """获取所有可用模型"""
    from agent import get_model_configurations

    model_configurations = get_model_configurations()
    return [
        {
            "modelName": model_name,
            "modelCode": model_name,
            "schemaList": [],
        }
        for model_name in model_configurations.keys()
    ]
