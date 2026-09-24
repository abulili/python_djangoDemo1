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

def route_agents(query):
    agents =  ["retriever"]

    if should_use_workflow_tool(query):
        agents.append("workflow")

    agents.append("answer")
    return agents

def run_retriever_agent(*, user, query, top_k, search_type):
    return retrieve_knowledge_tool(
        user=user,
        query=query,
        top_k=top_k,
        search_type=search_type,
    )

def run_workflow_agent(*, user):
    return get_workflow_summary_tool(user=user)

def run_answer_agent(
    *,
    user,
    query,
    conversation_id,
    model_key,
    trace_id,
    call_ai_service,
    memory_result,
    knowledge_result,
    workflow_result,
):
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
        else "本次问题未调用工作流 Agent"
    )

    prompt = f"""
你是 AnswerAgent，负责整合多个 Agent 的结果并给出最终业务回答。

【用户问题】
{query}

【会话记忆 Agent 结果】
{memory_context or "暂无会话记忆"}

【RetrieverAgent 知识库结果】
{knowledge_context or "暂无知识库命中"}

【WorkflowAgent 工作流结果】
{workflow_context}

回答要求：
1. 优先基于 RetrieverAgent 和 WorkflowAgent 的结果回答。
2. 不要编造 Agent 没有提供的数据。
3. 如果信息不足，请说明缺少哪些信息。
4. 回答要简洁、可用于业务判断。
"""

    result, success = call_ai_service(
        prompt=prompt,
        model_key=model_key,
        user=user,
    )

    return {
        "success": success,
        "prompt": prompt,
        "result": result,
        "answer": result.get("reply", ""),
    }

def run_multi_agent(
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

    selected_agents = route_agents(query)

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="multi_agent_start",
        query=query,
        detail={
            "selected_agents": selected_agents,
            "model": model_key,
            "top_k": top_k,
            "search_type": search_type,
        },
    )

    memory_result = get_conversation_memory_tool(
        user=user,
        conversation_id=conversation_id,
    )

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="multi_agent_memory",
        query=query,
        detail={
            "message_count": memory_result.get("message_count", 0),
            "returned_count": len(memory_result.get("messages", [])),
        },
    )

    knowledge_result = {
        "tool": "retrieve_knowledge",
        "results": [],
        "search_type": search_type,
        "top_k": top_k,
    }

    if "retriever" in selected_agents:
        knowledge_result = run_retriever_agent(
            user=user,
            query=query,
            top_k=top_k,
            search_type=search_type,
        )

        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="multi_agent_retriever",
            query=query,
            detail={
                "hit_count": len(knowledge_result.get("results", [])),
                "chunk_ids": [item["id"] for item in knowledge_result.get("results", [])],
            },
        )

    workflow_result = None

    if "workflow" in selected_agents:
        workflow_result = run_workflow_agent(user=user)

        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="multi_agent_workflow",
            query=query,
            detail={
                "my_request_count": workflow_result.get("my_request_count", 0),
                "pending_approval_count": workflow_result.get("pending_approval_count", 0),
            },
        )

    answer_result = run_answer_agent(
        user=user,
        query=query,
        conversation_id=conversation_id,
        model_key=model_key,
        trace_id=trace_id,
        call_ai_service=call_ai_service,
        memory_result=memory_result,
        knowledge_result=knowledge_result,
        workflow_result=workflow_result,
    )

    if not answer_result["success"]:
        AiTraceStepLog.objects.create(
            user=user,
            trace_id=trace_id,
            conversation_id=conversation_id,
            step="multi_agent_failed",
            query=query,
            success=False,
            error_message=answer_result["answer"],
            detail={
                "selected_agents": selected_agents,
            },
        )

        return {
            "success": False,
            "error": answer_result["answer"],
            "conversation_id": conversation_id,
            "agents": selected_agents,
            "references": knowledge_result.get("results", []),
        }

    answer = answer_result["answer"]

    AICallLog.objects.create(
        conversation_id=conversation_id,
        prompt=query,
        response=answer,
        duration=answer_result["result"].get("duration", 0.0),
        success=True,
        user=user,
        model_name=model_key,
        prompt_tokens=answer_result["result"].get("prompt_tokens", 0),
        completion_tokens=answer_result["result"].get("completion_tokens", 0),
        total_tokens=answer_result["result"].get("total_tokens", 0),
        cost=answer_result["result"].get("cost", 0.0),
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
        step="multi_agent_done",
        query=query,
        detail={
            "selected_agents": selected_agents,
            "answer_length": len(answer),
            "knowledge_hit_count": len(knowledge_result.get("results", [])),
            "used_workflow_agent": workflow_result is not None,
        },
    )

    return {
        "success": True,
        "query": query,
        "answer": answer,
        "conversation_id": conversation_id,
        "search_type": search_type,
        "agents": selected_agents,
        "references": knowledge_result.get("results", []),
        "framework": "multi-agent-router",
    }    

    


