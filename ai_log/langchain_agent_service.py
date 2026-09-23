import json
import uuid

from ai_log.agent_tools import (
    get_conversation_memory_tool,
    retrieve_knowledge_tool,
    get_workflow_summary_tool,
    should_use_workflow_tool,
)
from ai_log.models import AICallLog, AiTraceStepLog
from ai_log.services import save_conversation_messages_to_db

class LangChainStyleTool:
    """
    轻量 LangChain-style Tool。

    作用：
    1. 给每个工具统一 name / description / run。
    2. 方便以后替换成 langchain.tools.Tool。
    3. 让项目里能清楚体现“工具编排”。
    """

    def __init__(self, name, description, func):
        self.name = name
        self.description = description
        self.func = func

    def run(self, **kwargs):
        return self.func(**kwargs)

def build_langchain_style_tools():
    return [
        LangChainStyleTool(
            name="conversation_memory",
            description="读取当前 conversation_id 下的最近会话记忆",
            func=lambda user, query, conversation_id, top_k, search_type: get_conversation_memory_tool(user=user, conversation_id=conversation_id)
        ),
        LangChainStyleTool(
            name="knowledge_retriever",
            description="从知识库中按 keyword/vector/hybrid 检索相关片段",
            func=lambda user, query, conversation_id, top_k, search_type: retrieve_knowledge_tool(
                user=user,
                query=query,
                top_k=top_k,
                search_type=search_type,
            ),
        ),
        LangChainStyleTool(
            name="workflow_summary",
            description="读取当前用户的工作流申请、待审批和最近申请摘要",
            func=lambda user, query, conversation_id, top_k, search_type: get_workflow_summary_tool(
                user=user,
            ),
        ),
    ]

def run_langchain_style_agent(
    *,
    user,
    query,
    conversation_id,
    top_k,
    search_type,
    model_key,
    trace_id,
    call_ai_service,
):
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    
    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="langchain_agent_start",
        query=query,
        detail={
            "framework": "langchain-style",
            "top_k": top_k,
            "search_type": search_type,
            "model": model_key,
        },
    )

    tools = build_langchain_style_tools()
    tool_outputs = []
    memory_result = None
    knowledge_result = None
    workflow_result = None

    for tool in tools:
        if tool.name == "workflow_summary" and not should_use_workflow_tool(query):
            continue

        output = tool.run(
            user = user,
            query = query,
            conversation_id = conversation_id,
            top_k = top_k,
            search_type = search_type,
        )

        tool_outputs.append({
            "tool": tool.name,
            "description": tool.description,
            "output": output,
        })

        if tool.name == "conversation_memory":
            memory_result = output
            AiTraceStepLog.objects.create(
                user=user,
                trace_id=trace_id,
                conversation_id=conversation_id,
                step="langchain_tool_memory",
                query=query,
                detail={
                    "message_count": output["message_count"],
                    "returned_count": len(output["messages"]),
                },
            )

        if tool.name == "knowledge_retriever":
            knowledge_result = output
            AiTraceStepLog.objects.create(
                user=user,
                trace_id=trace_id,
                conversation_id=conversation_id,
                step="langchain_tool_retriever",
                query=query,
                detail={
                    "search_type": output["search_type"],
                    "top_k": output["top_k"],
                    "hit_count": len(output["results"]),
                    "chunk_ids": [item["id"] for item in output["results"]],
                },
            )

        if tool.name == "workflow_summary":
            workflow_result = output
            AiTraceStepLog.objects.create(
                user=user,
                trace_id=trace_id,
                conversation_id=conversation_id,
                step="langchain_tool_workflow",
                query=query,
                detail={
                    "my_request_count": output["my_request_count"],
                    "pending_approval_count": output["pending_approval_count"],
                    "recent_request_count": len(output["recent_requests"]),
                },
            )

    memory_result = memory_result or {
        "tool": "conversation_memory",
        "message_count": 0,
        "messages": [],
    }
    knowledge_result = knowledge_result or {
        "tool": "retrieve_knowledge",
        "results": [],
        "search_type": search_type,
        "top_k": top_k,
    }

    memory_context = "\n".join([
        f"{item.get('role')}: {item.get('content')}"
        for item in memory_result.get("messages", [])
    ])

    knowledge_context = "\n\n".join([
        f"资料{index + 1}：{item['content']}"
        for index, item in enumerate(knowledge_result.get("results", []))
    ])

    workflow_context = (
        json.dumps(workflow_result, ensure_ascii=False)
        if workflow_result
        else "本次问题未调用工作流工具"
    )

    tool_plan = [
        {
            "name": item["tool"],
            "description": item["description"],
        }
        for item in tool_outputs
    ]

    prompt = f"""
你是一个支持工具编排的业务 AI 助手。你正在使用 LangChain-style Agent 流程回答问题。

【工具计划】
{json.dumps(tool_plan, ensure_ascii=False)}

【会话记忆】
{memory_context or "暂无会话记忆"}

【知识库检索结果】
{knowledge_context or "暂无知识库命中"}

【工作流工具结果】
{workflow_context}

【用户问题】
{query}

回答要求：
1. 优先基于知识库和工具结果回答。
2. 如果使用了工作流工具，要结合申请数量、待审批数量、最近申请说明。
3. 不要编造工具结果里不存在的数据。
4. 回答要简洁、可用于业务判断。
"""
    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="langchain_prompt_build",
        query=query,
        detail={
            "prompt_length": len(prompt),
            "tool_count": len(tool_outputs),
            "knowledge_hit_count": len(knowledge_result.get("results", [])),
            "memory_message_count": memory_result.get("message_count", 0),
            "used_workflow": workflow_result is not None,
        },
    )

    result, success = call_ai_service(
        prompt=prompt,
        model_key=model_key,
        user=user,
    )

    if not success:
        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="langchain_agent_failed",
            query=query,
            success=False,
            error_message=result.get("reply", "AI 调用失败"),
            detail={
                "model": model_key,
                "framework": "langchain-style",
            },
        )

        return {
            "success": False,
            "error": result.get("reply", "AI 调用失败"),
            "conversation_id": conversation_id,
            "tools": tool_outputs,
            "references": knowledge_result.get("results", []),
        }

    answer = result.get("reply", "")

    AICallLog.objects.create(
        conversation_id=conversation_id,
        prompt=query,
        response=answer,
        duration=result.get("duration", 0.0),
        success=True,
        user=user,
        model_name=model_key,
        prompt_tokens=result.get("prompt_tokens", 0),
        completion_tokens=result.get("completion_tokens", 0),
        total_tokens=result.get("total_tokens", 0),
        cost=result.get("cost", 0.0),
        trace_id=trace_id,
    )

    save_conversation_messages_to_db(
        conversation_id=conversation_id,
        user=user,
        user_content=query,
        assistant_content=answer,
    )

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="langchain_agent_done",
        query=query,
        detail={
            "answer_length": len(answer),
            "tool_count": len(tool_outputs),
            "knowledge_hit_count": len(knowledge_result.get("results", [])),
            "total_tokens": result.get("total_tokens", 0),
            "cost": result.get("cost", 0.0),
            "framework": "langchain-style",
        },
    )

    return {
        "success": True,
        "query": query,
        "answer": answer,
        "conversation_id": conversation_id,
        "search_type": search_type,
        "tools": tool_outputs,
        "references": knowledge_result.get("results", []),
        "framework": "langchain-style",
    }


