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

from concurrent.futures import ThreadPoolExecutor, as_completed

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

def run_memory_agent(*, user, conversation_id):
    return get_conversation_memory_tool(
        user=user,
        conversation_id=conversation_id,
    )

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

    context_results = run_parallel_context_agents(
        selected_agents=selected_agents,
        user=user,
        query=query,
        conversation_id=conversation_id,
        top_k=top_k,
        search_type=search_type,
    )

    AiTraceStepLog.objects.create(
        user=user,
        trace_id=trace_id,
        conversation_id=conversation_id,
        step="multi_agent_parallel_context_done",
        query=query,
        detail={
            "parallel_agents": list(context_results.keys()),
            "parallel_agent_count": len(context_results),
        },
    )

    memory_result = context_results.get("memory") or {
        "tool": "conversation_memory",
        "message_count": 0,
        "messages": [],
    }

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

    knowledge_result = context_results.get("retriever") or {
        "tool": "retrieve_knowledge",
        "results": [],
        "search_type": search_type,
        "top_k": top_k,
    }

    if "retriever" in selected_agents:
        # knowledge_result = run_retriever_agent(
        #     user=user,
        #     query=query,
        #     top_k=top_k,
        #     search_type=search_type,
        # )

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

    workflow_result = context_results.get("workflow") or None

    if workflow_result:
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

def run_parallel_context_agents(
    *,
    selected_agents,
    user,
    query,
    conversation_id,
    top_k,
    search_type,
):
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_agent = {}

        # 这句不会直接返回结果，而是返回一个 Future = 任务收据 / 任务句柄
        # 我把任务交给线程池了，这是取结果用的小票
        memory_future = executor.submit(
            run_memory_agent,
            user=user,
            conversation_id=conversation_id,
        )
        future_to_agent[memory_future] = "memory"

        if "retriever" in selected_agents:
            retriever_future = executor.submit(
                run_retriever_agent,
                user=user,
                query=query,
                top_k=top_k,
                search_type=search_type,
            )
            future_to_agent[retriever_future] = "retriever"

        if "workflow" in selected_agents:
            workflow_future = executor.submit(
                run_workflow_agent,
                user=user,
            )
            future_to_agent[workflow_future] = "workflow"

        results = {}
        """
        tasks = {
            "memory": Future(...),
            "retriever": Future(...),
            "workflow": Future(...),
        }

        for future in as_completed(tasks.values()): 谁先执行完，就先把谁交出来
        as_completed(...) 会监听这些 Future，按完成顺序返回。
        memory      0.1s 完成
        workflow    0.3s 完成
        retriever   1.2s 完成

        memory_future
        workflow_future
        retriever_future
        """
        # tasks.values() 里一开始放的就是 Future 对象，也就是“已经提交出去、未来会完成的任务句柄
        """
        外层 for：每完成一个 future，就处理一次
        内层 next 里的 for：为了找这个 future 对应哪个 agent，再遍历 tasks
        """
        
        for future in as_completed(future_to_agent):
            # 反查这个完成的 future 对应哪个 agent 名字
            """
            next(...) 的作用是：从一个可迭代对象里取第一个结果。
            
            等价于
            for name, task_future in tasks.items():
                if task_future == future:
                    agent_name = name
                    break

            name for name, task_future in tasks.items() 会生成符合条件的 name

            name="memory", task_future=memory_future
            memory_future == retriever_future ? 否

            name="retriever", task_future=retriever_future
            retriever_future == retriever_future ? 是
            生成 "retriever"

            next(...) 拿到第一个生成的值："retriever"
            """
            # agent_name = next(
            #     name for name, task_future in tasks.items()
            #     if task_future == future
            # )
            agent_name = future_to_agent[future]
            # future.result() 取这个任务的返回值; 如果任务还没完成，就等它完成; 如果任务抛异常，这里会重新抛出来
            results[agent_name] = future.result()

    return results
    


